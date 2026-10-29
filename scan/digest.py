"""Write the scan as JSON (for tooling) and Markdown (for the editor)."""
import json
from dataclasses import asdict

SECTIONS = [
    ("Hacker News", "Hacker News"),
    ("Hugging Face Papers", "Hugging Face 每日论文"),
    ("GitHub", "GitHub 新仓库（近 7 天创建）"),
    ("rss", "实验室与作者博客"),
    ("reddit", "Reddit"),
]


def _section(item):
    if item.source.startswith("r/"):
        return "reddit"
    if item.source in {"Hacker News", "Hugging Face Papers", "GitHub"}:
        return item.source
    return "rss"


def to_json(scan):
    return json.dumps({
        "generated_at": scan["generated_at"].isoformat(),
        "window": {"start": scan["since"].isoformat(), "end": scan["generated_at"].isoformat(),
                   "tz": str(scan["generated_at"].tzinfo)},
        "errors": scan["errors"],
        "items": [{**asdict(i), "published": i.published.isoformat(), "section": _section(i),
                   "seen_in": scan["seen"][id(i)]} for i in scan["items"]],
    }, ensure_ascii=False, indent=2)


def _meta(item, tz):
    bits = [item.source, item.published.astimezone(tz).strftime("%m-%d %H:%M")]
    if item.score is not None:
        unit = {"GitHub": "stars", "Hugging Face Papers": "upvotes"}.get(item.source, "points")
        bits.append(f"{item.score} {unit}")
    if item.comments:
        bits.append(f"{item.comments} comments")
    return " · ".join(bits)


def to_markdown(scan):
    tz = scan["generated_at"].tzinfo
    items = scan["items"]
    repeat = sum(1 for i in items if scan["seen"][id(i)])
    lines = [
        f"# 宽扫候选 {scan['generated_at']:%Y-%m-%d}",
        "",
        f"窗口：{scan['since']:%Y-%m-%d %H:%M} 至 {scan['generated_at']:%Y-%m-%d %H:%M}（{tz}）。"
        f"共 {len(items)} 条，其中 {repeat} 条已在往期简报引用过，需要确认有新的事件增量才能再收。",
        "",
        "这是候选清单，不是简报：每条都要回到原始来源核实（内容方法第 3–4 步）。",
    ]
    if scan["errors"]:
        lines += ["", "**未覆盖的来源**（抓取失败，这些渠道需要手动补扫）："]
        lines += [f"- {name}: {err}" for name, err in sorted(scan["errors"].items())]
    for key, heading in SECTIONS:
        group = [i for i in items if _section(i) == key]
        if not group:
            continue
        lines += ["", f"## {heading}（{len(group)}）", ""]
        for i in group:
            lines.append(f"- [{i.title}]({i.url})  ")
            lines.append(f"  {_meta(i, tz)}")
            if i.excerpt:
                lines.append(f"  > {i.excerpt}")
            if scan["seen"][id(i)]:
                lines.append(f"  已引用：{'、'.join(scan['seen'][id(i)])}")
    return "\n".join(lines) + "\n"
