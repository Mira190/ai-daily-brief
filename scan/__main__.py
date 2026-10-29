"""python -m scan: collect wide-scan candidates for today's brief.

Writes scan-output/<date>.json and .md (gitignored: research caches stay out of
the public repo, see SECURITY.md). Exits 1 when nothing was found and a source failed.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import archive, digest, sources

ROOT = Path(__file__).resolve().parent.parent


def run(opts, http=None, now=None):
    tz = ZoneInfo(opts.tz)
    now = now or datetime.now(tz)
    since = now - timedelta(hours=opts.hours)
    http = http or sources.Http()
    items, errors = [], {}
    for name in opts.sources:
        try:
            result = sources.FETCHERS[name](http, since, opts)
        except Exception as e:
            errors[name] = str(e)
            continue
        if isinstance(result, tuple):
            result, sub_errors = result
            errors.update(sub_errors)
        items += result
    index = Path(opts.archive)
    cited = archive.cited_links(index.read_text(encoding="utf-8")) if index.exists() else {}
    return {"generated_at": now, "since": since, "items": items, "errors": errors,
            "seen": {id(i): archive.seen_in(i, cited) for i in items}}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m scan", description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=int, default=24, help="window length (default 24)")
    parser.add_argument("--tz", default="Australia/Sydney")
    parser.add_argument("--sources", type=lambda s: s.split(","), default=list(sources.FETCHERS),
                        help=f"comma list of {','.join(sources.FETCHERS)}")
    parser.add_argument("--archive", default=str(ROOT / "index.html"), help="published archive used for dedupe")
    parser.add_argument("--out", default=str(ROOT / "scan-output"))
    parser.add_argument("--hn-min-points", type=int, default=30)
    parser.add_argument("--github-min-stars", type=int, default=50)
    opts = parser.parse_args(argv)
    unknown = set(opts.sources) - set(sources.FETCHERS)
    if unknown:
        parser.error(f"unknown sources: {', '.join(sorted(unknown))}")

    scan = run(opts)
    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"{scan['generated_at']:%Y-%m-%d}"
    stem.with_suffix(".json").write_text(digest.to_json(scan), encoding="utf-8")
    stem.with_suffix(".md").write_text(digest.to_markdown(scan), encoding="utf-8")
    print(f"{len(scan['items'])} candidates, {len(scan['errors'])} source errors -> {stem}.md")
    for name, err in sorted(scan["errors"].items()):
        print(f"  failed: {name}: {err}", file=sys.stderr)
    return 1 if not scan["items"] and scan["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
