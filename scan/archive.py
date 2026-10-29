"""Links already cited by published briefs, for event-increment dedupe (README 内容方法 step 5)."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ARTICLE = re.compile(r'<article\b[^>]*data-date="([^"]+)"[^>]*>([\s\S]*?)</article>')
HREF = re.compile(r'href="(https?://[^"]+)"')
ARXIV = re.compile(r"^(?:arxiv\.org/(?:abs|pdf|html)|huggingface\.co/papers)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$")
TRACKING = {"ref", "ref_src", "fbclid", "gclid"}


def normalize(url):
    parts = urlsplit(url.replace("&amp;", "&"))
    host = parts.netloc.lower().removeprefix("www.").removeprefix("old.")
    path = parts.path.rstrip("/")
    paper = ARXIV.match(f"{host}{path}")
    if paper:
        return f"arxiv:{paper.group(1)}"
    query = [(k, v) for k, v in parse_qsl(parts.query) if not (k.lower().startswith("utm_") or k.lower() in TRACKING)]
    return urlunsplit(("", host, path, urlencode(query), "")).lstrip("/")


def cited_links(index_html):
    """normalized url -> sorted brief dates that link to it"""
    cited = {}
    for date, body in ARTICLE.findall(index_html):
        for href in HREF.findall(body):
            cited.setdefault(normalize(href), set()).add(date)
    return {url: sorted(dates) for url, dates in cited.items()}


def seen_in(item, cited):
    dates = set()
    for url in [item.url, *item.alt_urls]:
        dates.update(cited.get(normalize(url), ()))
    return sorted(dates)
