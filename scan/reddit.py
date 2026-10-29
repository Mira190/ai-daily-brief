"""Reddit, read at the pace Reddit allows anonymous readers.

An anonymous client gets about one request per rate-limit window:
x-ratelimit-remaining drops to 0 after a single call and x-ratelimit-reset says
when it refills. So subreddits are read one at a time, waiting out each reset
plus a few seconds, like a person clicking through. Each subreddit's result is
cached for CACHE_HOURS, and a wait longer than MAX_WAIT (or past BUDGET in
total) is not sat out: the remaining subreddits are left for the next run,
which reads only what is missing or stale. Several runs over a day fill the
picture in bit by bit.
"""
import json
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .sources import Item, parse_feed

SUBREDDITS = ["LocalLLaMA", "MachineLearning", "ClaudeAI", "ChatGPT"]
CACHE_HOURS = 3
MAX_WAIT = 90  # seconds; longer than this, defer to the next run
BUDGET = 300  # seconds of waiting per run in total
GAP = (4, 9)  # extra seconds on top of the reset, so requests never line up back to back
PER_SUB = 5


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


def fetch(http, since, cache_dir, sleep=time.sleep, now=lambda: datetime.now(timezone.utc),
          jitter=random.uniform, log=_log):
    cache = Cache(cache_dir, now)
    items, errors = [], {}
    wait = waited = 0.0
    for sub in SUBREDDITS:
        name = f"r/{sub}"
        cached = cache.load(sub, since)
        if cached is not None:
            items += cached
            continue
        res = None
        for attempt in range(2):
            if wait > MAX_WAIT or waited + wait > BUDGET:
                break
            if wait:
                log(f"{name}: waiting {wait:.0f}s for Reddit's rate limit")
                sleep(wait)
                waited += wait
            # the JSON API answers 403 without OAuth; the RSS view does not
            res = http.get(f"https://www.reddit.com/r/{sub}/top/.rss?t=day")
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
        got = parse_feed(res.content, since, name, PER_SUB)
        cache.save(sub, got)
        items += got
    return items, errors
