import argparse
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scan import __main__ as cli
from scan import archive, digest, sources

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


def rss(*entries):
    body = "".join(f"<item><title>{t}</title><link>{l}</link>{f'<pubDate>{d}</pubDate>' if d else ''}"
                   f"<description>&lt;p&gt;{s}&lt;/p&gt;</description></item>" for t, l, d, s in entries)
    return f"<rss version='2.0'><channel><title>x</title>{body}</channel></rss>".encode()


class FakeHttp:
    def __init__(self, json=None, raw=None):
        self.json, self.raw = json or {}, raw or {}

    def get_json(self, url, params=None):
        value = self.json[url]
        if isinstance(value, Exception):
            raise value
        return value(params) if callable(value) else value

    def get_bytes(self, url):
        value = self.raw.get(url, rss())
        if isinstance(value, Exception):
            raise value
        return value


class KeywordTest(unittest.TestCase):
    def test_whole_words_only(self):
        # the old substring match counted these as AI stories
        for title in ["Warn about PyPy being unmaintained", "Living human brain cells play DOOM", "Chromatron",
                      "Leak exposes undercover ICE agents"]:
            self.assertIsNone(sources.AI_TERMS.search(title), title)
        for title in ["Show HN: an MCP server", "LLMs can't count", "Claude 5 system card", "AI agents in CI",
                      "The Agent SDK", "Agentic coding at scale"]:
            self.assertIsNotNone(sources.AI_TERMS.search(title), title)


class FeedTest(unittest.TestCase):
    def test_window_and_missing_dates(self):
        http = FakeHttp(raw={"u": rss(
            ("new", "https://a.dev/new", "Thu, 29 Oct 2026 23:00:00 GMT", "fresh <b>post</b>"),
            ("old", "https://a.dev/old", "Mon, 26 Oct 2026 10:00:00 GMT", ""),
            ("undated", "https://a.dev/undated", None, ""),
        )})
        items = sources.fetch_feed(http, SINCE, "Blog", "u")
        self.assertEqual([i.title for i in items], ["new"])
        self.assertEqual(items[0].excerpt, "fresh post")
        self.assertEqual(items[0].published, datetime(2026, 10, 29, 23, tzinfo=timezone.utc))

    def test_one_failing_feed_does_not_hide_the_others(self):
        good = rss(("ok", "https://b.dev/ok", "Thu, 29 Oct 2026 23:00:00 GMT", ""))
        raw = {url: good for _, url in sources.RSS_FEEDS}
        raw[sources.RSS_FEEDS[0][1]] = ConnectionError("down")
        items, errors = sources.fetch_rss(FakeHttp(raw=raw), SINCE)
        self.assertEqual(len(items), len(sources.RSS_FEEDS) - 1)
        self.assertEqual(list(errors), [sources.RSS_FEEDS[0][0]])


class HackerNewsTest(unittest.TestCase):
    def test_filters_titles_and_keeps_discussion_link(self):
        hits = [
            {"title": "Claude agents in production", "url": "https://x.dev/p", "objectID": "1",
             "points": 300, "num_comments": 80, "created_at": "2026-10-29T20:00:00Z"},
            {"title": "Ask HN: LLM evals?", "url": None, "objectID": "2", "points": 90,
             "num_comments": 40, "created_at": "2026-10-29T21:00:00Z", "story_text": "<p>How do you</p>"},
            {"title": "A new SQLite release", "url": "https://sqlite.org", "objectID": "3",
             "points": 500, "num_comments": 10, "created_at": "2026-10-29T22:00:00Z"},
        ]
        http = FakeHttp(json={"https://hn.algolia.com/api/v1/search": {"hits": hits}})
        items = sources.fetch_hacker_news(http, SINCE)
        self.assertEqual([i.title for i in items], ["Claude agents in production", "Ask HN: LLM evals?"])
        self.assertEqual(items[0].alt_urls, ["https://news.ycombinator.com/item?id=1"])
        self.assertEqual(items[1].url, "https://news.ycombinator.com/item?id=2")
        self.assertEqual(items[1].alt_urls, [])


class HuggingFacePapersTest(unittest.TestCase):
    def test_unpublished_day_is_skipped(self):
        paper = {"publishedAt": "2026-10-29T07:00:00.000Z", "numComments": 2,
                 "paper": {"id": "2610.00001", "title": "A paper", "upvotes": 40, "summary": "s"}}

        since = datetime.now(timezone.utc) - timedelta(days=1)

        def daily(params):
            # yesterday's list is out, today's is not yet
            return [paper] if params["date"] == since.date().isoformat() else {"error": "not published"}

        http = FakeHttp(json={"https://huggingface.co/api/daily_papers": daily})
        items = sources.fetch_hf_papers(http, since)
        self.assertEqual([(i.url, i.alt_urls) for i in items],
                         [("https://huggingface.co/papers/2610.00001", ["https://arxiv.org/abs/2610.00001"])])


class GitHubTest(unittest.TestCase):
    def test_drops_undescribed_and_duplicate_repos(self):
        repo = lambda name, stars, desc: {"full_name": name, "html_url": f"https://github.com/{name}",
                                          "created_at": "2026-10-28T00:00:00Z", "stargazers_count": stars,
                                          "description": desc}
        data = {"items": [repo("a/tool", 900, "An agent tool"), repo("spam/lure", 800, None)]}
        http = FakeHttp(json={"https://api.github.com/search/repositories": data})
        items = sources.fetch_github(http, SINCE)
        self.assertEqual([i.title for i in items], ["a/tool"])


class ArchiveTest(unittest.TestCase):
    HTML = ('<article class="brief" data-date="2026-09-26"><a href="https://arxiv.org/pdf/2609.01234v2">p</a>'
            '<a href="https://www.example.com/post/?utm_source=x&amp;id=7">e</a></article>'
            '<article class="brief" data-date="2026-09-27"><a href="https://huggingface.co/papers/2609.01234">p</a>'
            '</article>')

    def test_paper_links_and_tracking_params_match(self):
        cited = archive.cited_links(self.HTML)
        paper = sources.Item("HF", "p", "https://huggingface.co/papers/2609.01234", NOW,
                             alt_urls=["https://arxiv.org/abs/2609.01234"])
        post = sources.Item("Blog", "e", "https://example.com/post?id=7", NOW)
        fresh = sources.Item("Blog", "f", "https://example.com/other", NOW)
        self.assertEqual(archive.seen_in(paper, cited), ["2026-09-26", "2026-09-27"])
        self.assertEqual(archive.seen_in(post, cited), ["2026-09-26"])
        self.assertEqual(archive.seen_in(fresh, cited), [])


class CliTest(unittest.TestCase):
    def test_run_marks_repeats_and_reports_failed_sources(self):
        with TemporaryDirectory() as tmp:
            index = Path(tmp, "index.html")
            index.write_text('<article data-date="2026-09-27"><a href="https://x.dev/p">p</a></article>',
                             encoding="utf-8")
            hits = [{"title": "AI thing", "url": "https://x.dev/p", "objectID": "1", "points": 50,
                     "num_comments": 3, "created_at": "2026-10-29T20:00:00Z"}]
            http = FakeHttp(json={"https://hn.algolia.com/api/v1/search": {"hits": hits},
                                  "https://api.github.com/search/repositories": RuntimeError("rate limited")})
            opts = argparse.Namespace(tz="Australia/Sydney", hours=24, sources=["hn", "github"],
                                      archive=str(index), hn_min_points=30, github_min_stars=50)
            scan = cli.run(opts, http=http, now=NOW)
            md = digest.to_markdown(scan)
            self.assertIn("已引用：2026-09-27", md)
            self.assertIn("- github: rate limited", md)
            self.assertIn('"seen_in": [\n        "2026-09-27"\n      ]', digest.to_json(scan))


if __name__ == "__main__":
    unittest.main()
