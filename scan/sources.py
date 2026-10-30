"""Candidate fetchers for the wide-scan step (README 内容方法 step 2).

Each fetcher takes an Http client and the start of the window, and returns
Items published inside the window. Fetchers never invent a date: an entry
without one is dropped rather than treated as new.
"""
import html
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import feedparser
import requests

USER_AGENT = "ai-daily-brief-scan/0.1 (+https://github.com/Mira190/ai-daily-brief)"
TIMEOUT = 20

AI_TERMS = re.compile(
    r"\b(ai|a\.i\.|agi|llms?|gpt[\w.-]*|chatgpt|claude|openai|anthropic|gemini|deepmind|deepseek|qwen|"
    r"llama|mistral|agentic|coding agents?|agent sdk|copilot|cursor|mcp|rag|embeddings?|transformers?|diffusion|"
    r"inference|fine-?tun\w*|machine learning|deep learning|neural|reasoning models?|benchmarks?)\b",
    re.I,
)

RSS_FEEDS = [
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("OpenAI News", "https://openai.com/news/rss.xml"),
    ("Google DeepMind Blog", "https://deepmind.google/blog/rss.xml"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
]
GITHUB_TOPICS = ["llm", "ai-agents", "mcp"]


@dataclass
class Item:
    source: str
    title: str
    url: str
    published: datetime
    score: int | None = None
    comments: int | None = None
    excerpt: str = ""
    alt_urls: list[str] = field(default_factory=list)


class Http:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get_json(self, url, params=None):
        headers = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token and url.startswith("https://api.github.com/"):
            headers["Authorization"] = f"Bearer {token}"
        res = self.session.get(url, params=params, headers=headers, timeout=TIMEOUT)
        res.raise_for_status()
        return res.json()

    def get_bytes(self, url):
        res = self.get(url)
        res.raise_for_status()
        return res.content

    def get(self, url, params=None, headers=None):
        """The raw response, for callers that read status and rate-limit headers themselves."""
        return self.session.get(url, params=params, headers=headers, timeout=TIMEOUT)

    def post(self, url, data, auth=None, headers=None):
        return self.session.post(url, data=data, auth=auth, headers=headers, timeout=TIMEOUT)


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(markup, limit=280):
    parser = _TextOnly()
    parser.feed(html.unescape(markup or ""))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_iso(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _entry_time(entry):
    # feedparser normalises *_parsed to UTC
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_feed(http, since, name, url, limit=10):
    return parse_feed(http.get_bytes(url), since, name, limit)


def parse_feed(content, since, name, limit=10):
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        published = _entry_time(entry)
        if published is None or published < since or not entry.get("link"):
            continue
        items.append(Item(name, plain_text(entry.get("title"), 200), entry["link"], published,
                          excerpt=plain_text(entry.get("summary"))))
    items.sort(key=lambda i: i.published, reverse=True)
    return items[:limit]


def fetch_rss(http, since):
    items, errors = [], {}
    for name, url in RSS_FEEDS:
        try:
            items += fetch_feed(http, since, name, url)
        except Exception as e:
            errors[name] = str(e)
    try:
        items += fetch_anthropic(http, since)
    except Exception as e:
        errors["Anthropic News"] = str(e)
    return items, errors


SITEMAP_URL = re.compile(r"<url>\s*<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
OG_TITLE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"')


def fetch_anthropic(http, since, limit=5):
    """anthropic.com/news has no feed; its sitemap's lastmod finds new or updated posts (robots.txt allows /)."""
    sitemap = http.get_bytes("https://www.anthropic.com/sitemap.xml").decode("utf-8", "replace")
    recent = sorted(((_parse_iso(mod), loc) for loc, mod in SITEMAP_URL.findall(sitemap)
                     if "/news/" in loc and _parse_iso(mod) >= since), reverse=True)[:limit]
    items = []
    for modified, url in recent:
        title = OG_TITLE.search(http.get_bytes(url).decode("utf-8", "replace"))
        title = title.group(1) if title else url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        # the pages' descriptions are the site boilerplate; lastmod also moves on edits, so say so
        items.append(Item("Anthropic News", plain_text(title, 200), url, modified,
                          excerpt="(sitemap lastmod: new or edited)"))
    return items


def fetch_hacker_news(http, since, min_points=30):
    data = http.get_json("https://hn.algolia.com/api/v1/search", {
        "tags": "story",
        "numericFilters": f"created_at_i>{int(since.timestamp())},points>={min_points}",
        "hitsPerPage": 200,
    })
    items = []
    for hit in data.get("hits", []):
        title = hit.get("title") or ""
        if not AI_TERMS.search(title):
            continue
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        url = hit.get("url") or discussion
        items.append(Item("Hacker News", title, url, _parse_iso(hit["created_at"]),
                          score=hit.get("points"), comments=hit.get("num_comments"),
                          excerpt=plain_text(hit.get("story_text")),
                          alt_urls=[discussion] if url != discussion else []))
    items.sort(key=lambda i: i.score or 0, reverse=True)
    return items[:20]


def fetch_hf_papers(http, since):
    items, seen = [], set()
    day = since.astimezone(timezone.utc).date()
    while day <= datetime.now(timezone.utc).date():
        entries = http.get_json("https://huggingface.co/api/daily_papers", {"date": day.isoformat()})
        # a day whose list is not published yet answers with an error object
        for entry in entries if isinstance(entries, list) else []:
            paper = entry.get("paper", {})
            pid = paper.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            published = _parse_iso(entry.get("publishedAt") or paper.get("publishedAt"))
            if published is None:
                continue
            items.append(Item("Hugging Face Papers", plain_text(paper.get("title"), 200),
                              f"https://huggingface.co/papers/{pid}", published,
                              score=paper.get("upvotes"), comments=entry.get("numComments"),
                              excerpt=plain_text(paper.get("summary")),
                              alt_urls=[f"https://arxiv.org/abs/{pid}"]))
        day += timedelta(days=1)
    items.sort(key=lambda i: i.score or 0, reverse=True)
    return items[:15]


def fetch_github(http, since, min_stars=50):
    # New repos only: "trending" without an auth'd API means stars gained on a young repo.
    created = since.astimezone(timezone.utc) - timedelta(days=6)
    found = {}
    for topic in GITHUB_TOPICS:
        data = http.get_json("https://api.github.com/search/repositories", {
            "q": f"topic:{topic} created:>{created:%Y-%m-%d} stars:>={min_stars}",
            "sort": "stars", "order": "desc", "per_page": 10,
        })
        for repo in data.get("items", []):
            # undescribed young repos are mostly spam or malware lures
            if not repo.get("description") or repo["full_name"] in found:
                continue
            found[repo["full_name"]] = Item("GitHub", repo["full_name"], repo["html_url"],
                                            _parse_iso(repo["created_at"]), score=repo["stargazers_count"],
                                            excerpt=plain_text(repo["description"]))
    return sorted(found.values(), key=lambda i: i.score or 0, reverse=True)[:10]
