"""Reddit, through its official Data API only.

Reddit's robots.txt disallows all anonymous crawling (User-agent: * /
Disallow: /) and its Public Content Policy points programmatic readers to the
Data API, so this needs a registered app: set REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET (a "script" app at https://www.reddit.com/prefs/apps) and
REDDIT_USERNAME for the User-Agent Reddit asks for. Without them the source is
reported as not covered; it never falls back to scraping.

Requests still follow the rate-limit headers: subreddits are read one at a
time, waiting out x-ratelimit-reset when the budget is spent. Each subreddit's
result is cached for CACHE_HOURS, and a wait longer than MAX_WAIT (or past
BUDGET in total) is not sat out: the remaining subreddits are left for the next
run, which reads only what is missing or stale.
"""
import json
import os
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .sources import Item, plain_text

SUBREDDITS = ["LocalLLaMA", "MachineLearning", "ClaudeAI", "ChatGPT"]
CACHE_HOURS = 3
MAX_WAIT = 90  # seconds; longer than this, defer to the next run
BUDGET = 300  # seconds of waiting per run in total
GAP = (1, 3)  # extra seconds between requests
PER_SUB = 5
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
NOT_CONFIGURED = ("not configured: set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (Reddit's robots.txt "
                  "disallows anonymous crawling, so only the official Data API is used)")


def _log(msg):
    print(msg, file=sys.stderr)


def wait_for(headers):
    """Seconds until Reddit will accept the next request."""
    retry = headers.get("retry-after", "")
    if retry.isdigit():
        return int(retry)
    try:
        if float(headers.get("x-ratelimit-remaining", "1")) < 1:
            return float(headers.get("x-ratelimit-reset", "60"))
    except ValueError:
        return 60
    return 0


class Cache:
    def __init__(self, root, now):
        self.root, self.now = root, now

    def _path(self, sub):
        return self.root / f"reddit-{sub}.json"

    def load(self, sub, since):
        """Items still inside the window, or None when there is no fresh copy."""
        try:
            data = json.loads(self._path(sub).read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(data["fetched_at"])
        except (OSError, ValueError, KeyError):
            return None
        if self.now() - fetched > timedelta(hours=CACHE_HOURS):
            return None
        items = [Item(**{**i, "published": datetime.fromisoformat(i["published"])}) for i in data["items"]]
        return [i for i in items if i.published >= since]

    def save(self, sub, items):
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(sub).write_text(json.dumps({
            "fetched_at": self.now().isoformat(),
            "items": [{**asdict(i), "published": i.published.isoformat()} for i in items],
        }, ensure_ascii=False), encoding="utf-8")


def user_agent(username):
    # the format Reddit's API rules ask for
    return f"python:ai-daily-brief-scan:0.2 (by /u/{username or 'unknown'})"


def parse_listing(data, since, name):
    items = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied") or not post.get("permalink"):
            continue
        published = datetime.fromtimestamp(post["created_utc"], timezone.utc)
        if published < since:
            continue
        link = f"https://www.reddit.com{post['permalink']}"
        external = post.get("url_overridden_by_dest") or ""
        items.append(Item(name, plain_text(post.get("title"), 200), link, published,
                          score=post.get("score"), comments=post.get("num_comments"),
                          excerpt=plain_text(post.get("selftext")),
                          alt_urls=[external] if external and "reddit.com" not in external else []))
    items.sort(key=lambda i: i.score or 0, reverse=True)
    return items[:PER_SUB]


def token(http, env, headers):
    res = http.post(TOKEN_URL, {"grant_type": "client_credentials"},
                    auth=(env["REDDIT_CLIENT_ID"], env["REDDIT_CLIENT_SECRET"]), headers=headers)
    res.raise_for_status()
    return res.json()["access_token"]


def fetch(http, since, cache_dir, env=None, sleep=time.sleep, now=lambda: datetime.now(timezone.utc),
          jitter=random.uniform, log=_log):
    env = os.environ if env is None else env
    cache = Cache(cache_dir, now)
    items, errors, todo = [], {}, []
    for sub in SUBREDDITS:
        cached = cache.load(sub, since)
        if cached is None:
            todo.append(sub)
        else:
            items += cached
    if not todo:
        return items, errors
    if not (env.get("REDDIT_CLIENT_ID") and env.get("REDDIT_CLIENT_SECRET")):
        return items, {"reddit": NOT_CONFIGURED}
    headers = {"User-Agent": user_agent(env.get("REDDIT_USERNAME"))}
    headers["Authorization"] = f"Bearer {token(http, env, headers)}"
    wait = waited = 0.0
    for sub in todo:
        name = f"r/{sub}"
        res = None
        for attempt in range(2):
            if wait > MAX_WAIT or waited + wait > BUDGET:
                break
            if wait:
                log(f"{name}: waiting {wait:.0f}s for Reddit's rate limit")
                sleep(wait)
                waited += wait
            res = http.get(f"https://oauth.reddit.com/r/{sub}/top", {"t": "day", "limit": 25}, headers)
            wait = wait_for(res.headers) + jitter(*GAP)
            if res.status_code != 429:
                break
        if res is None or res.status_code == 429:
            errors[name] = (f"rate limited; left for the next run (Reddit asks to wait {wait:.0f}s, "
                            f"{waited:.0f}s already spent waiting this run)")
            continue
        if res.status_code != 200:
            errors[name] = f"HTTP {res.status_code}"
            continue
        got = parse_listing(res.json(), since, name)
        cache.save(sub, got)
        items += got
    return items, errors
