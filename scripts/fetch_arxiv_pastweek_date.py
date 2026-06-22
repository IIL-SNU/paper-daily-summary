#!/usr/bin/env python3
"""Fetch one date section from arXiv /pastweek.

Usage:
    python scripts/fetch_arxiv_pastweek_date.py cs.LG 2026-05-11 > out/cs.LG_new.json

This is for backfilling a weekday after /new has advanced.  /pastweek list
pages do not include abstracts, so generated backfills are title/subject based.
"""
from __future__ import annotations

import calendar
import datetime as dt
import io
import json
import re
import sys
import urllib.request

from fetch_arxiv import parse_papers

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


UA = "Mozilla/5.0 (paper-daily-summary helper)"
SECTION_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.I | re.S)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def arxiv_date_label(date_str: str) -> str:
    day = dt.date.fromisoformat(date_str)
    return f"{calendar.day_abbr[day.weekday()]}, {day.day} {calendar.month_abbr[day.month]} {day.year}"


def date_block(html: str, date_str: str) -> str:
    label = arxiv_date_label(date_str)
    matches = list(SECTION_RE.finditer(html))
    for idx, match in enumerate(matches):
        title = strip_tags(match.group(1))
        if label in title:
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
            return html[match.start():end]
    raise SystemExit(f"date section not found: {label}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    cat = sys.argv[1]
    date_str = sys.argv[2]
    url = f"https://arxiv.org/list/{cat}/pastweek?skip=0&show=2000"
    block = date_block(fetch(url), date_str)
    papers = parse_papers(block, include_abstract=False)
    print(json.dumps(papers, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
