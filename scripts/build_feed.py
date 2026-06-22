"""
Build RSS 2.0 feed.xml from posts/*.html.

- Scans all posts/YYYY-MM-DD.html in the repo (script is expected to run from repo root).
- Extracts title (<h1>) and summary (first <p> under "주간 동향" h2) from each.
- Emits feed.xml at repo root so GitHub Pages serves it at /feed.xml.

Usage:
    python scripts/build_feed.py          # writes feed.xml
    python scripts/build_feed.py --check  # prints item count, no file write

Idempotent. No external dependencies (stdlib only).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

SITE_URL = os.environ.get("SITE_URL", "https://iilab.io/paper-daily-summary")
FEED_TITLE = "Imaging Intelligence Daily Briefing — computational optical imaging"
FEED_DESC = (
    "cs.LG · cs.CV · cs.AI · eess.IV · eess.SP arXiv new submissions and Crossref "
    "journal articles, bucketed by lab ROI (Fourier Ptychography/Microscopy, "
    "Lensless/Coded Imaging, Phase Imaging/Holography, Meta-Optics/Diffractive, "
    "Light-Field/Novel Sensors, Tomography/3D Imaging, Virtual Staining/Pathology, "
    "Reconstruction/Inverse Problems, Deep Learning Methods). Daily briefing with insights."
)
FEED_LANG = "ko"
MAX_ITEMS = 60  # newest N posts
KST = timezone(timedelta(hours=9))

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(-weekly)?\.html$")


def strip_tags(s: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def extract_title(doc: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", doc, re.S)
    return strip_tags(m.group(1)) if m else ""


def extract_summary(doc: str, max_len: int = 380) -> str:
    """First <p> paragraph following the 🔭 주간 동향 h2."""
    m = re.search(r"<h2[^>]*>.*?주간 동향.*?</h2>(.*?)(?:<h2|$)", doc, re.S)
    if not m:
        return ""
    block = m.group(1)
    p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
    if not p:
        return ""
    text = strip_tags(p.group(1))
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def rfc822(dt: datetime) -> str:
    """RFC 822 formatted datetime for pubDate."""
    # locale-independent: use English day/month names by strftime('%a','%b')
    # on some platforms strftime uses locale, so hand-format:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    day = days[dt.weekday()]
    mon = months[dt.month - 1]
    return f"{day}, {dt.day:02d} {mon} {dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0900"


def build_item(date_str: str, title: str, summary: str, suffix: str = "") -> str:
    y, m, d = map(int, date_str.split("-"))
    # Publish "time" pinned to 09:00 KST on that date (matches daily briefing schedule).
    pub = datetime(y, m, d, 9, 0, 0, tzinfo=KST)
    url = f"{SITE_URL}/posts/{date_str}{suffix}.html"
    desc_body = summary if summary else f"arXiv Daily Briefing {date_str}"
    # CDATA to let HTML entities pass through readers cleanly
    desc_cdata = f"<![CDATA[{desc_body}]]>"
    return (
        "    <item>\n"
        f"      <title>{xml_escape(title)}</title>\n"
        f"      <link>{url}</link>\n"
        f"      <guid isPermaLink=\"true\">{url}</guid>\n"
        f"      <pubDate>{rfc822(pub)}</pubDate>\n"
        f"      <description>{desc_cdata}</description>\n"
        "    </item>"
    )


def collect_posts(repo_root: Path) -> list[tuple[str, str, str, str]]:
    posts_dir = repo_root / "posts"
    if not posts_dir.is_dir():
        return []
    entries: list[tuple[str, str, str, str]] = []
    for p in posts_dir.iterdir():
        m = DATE_RE.match(p.name)
        if not m:
            continue
        date_str = m.group(1)
        suffix = m.group(2) or ""
        try:
            doc = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            doc = p.read_text(encoding="utf-8", errors="replace")
        title = extract_title(doc) or f"arXiv Daily Briefing — {date_str}"
        summary = extract_summary(doc)
        entries.append((date_str, title, summary, suffix))
    # Sort by date (desc), weekly suffix wins on tie (so weekly entry of same date comes before daily — though we don't expect both)
    entries.sort(key=lambda x: (x[0], x[3]), reverse=True)
    return entries[:MAX_ITEMS]


def build_feed(repo_root: Path) -> str:
    items = collect_posts(repo_root)
    last_build = rfc822(datetime.now(tz=KST))
    items_xml = "\n".join(build_item(*e) for e in items) if items else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{xml_escape(FEED_TITLE)}</title>\n"
        f"    <link>{SITE_URL}/</link>\n"
        f'    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml" />\n'
        f"    <description>{xml_escape(FEED_DESC)}</description>\n"
        f"    <language>{FEED_LANG}</language>\n"
        f"    <lastBuildDate>{last_build}</lastBuildDate>\n"
        f"    <ttl>720</ttl>\n"
        f"{items_xml}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Print item count, do not write")
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    feed = build_feed(repo)
    count = feed.count("<item>")

    if args.check:
        print(f"[build_feed] {count} items discovered under {repo}/posts/")
        return 0

    out = repo / "feed.xml"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(feed)
    print(f"[build_feed] wrote {out} with {count} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
