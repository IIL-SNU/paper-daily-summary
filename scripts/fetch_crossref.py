#!/usr/bin/env python3
"""Fetch recent journal articles from the Crossref REST API.

Outputs the SAME JSON schema as fetch_arxiv.py (so classify.py and the
downstream briefing pipeline treat journal papers identically), plus a few
journal-specific fields (source, doi, journal, url, published, created).

Two query modes (combinable; --query and --issn are both repeatable):
  1. Keyword  : --query "Fourier ptychography" --query "lensless imaging"
                (each runs separately and results merge — good for a lab spanning
                 several distinct sub-topics)
  2. Journals : --issn 1552-3098 --issn 0278-3649 (one or more venue ISSNs)

Usage:
    python scripts/fetch_crossref.py --query "computational microscopy" --days 14 > out/journal_new.json
    python scripts/fetch_crossref.py --query "Fourier ptychography" --query "virtual staining" --days 30 > out/journal_new.json
    python scripts/fetch_crossref.py --issn 1361-8415 --days 30 > out/journal_new.json

Notes:
  - Crossref abstracts are JATS XML and frequently ABSENT (~50% coverage).
    When missing, classification falls back to the title only.
  - `--days N` filters by Crossref *created* (DOI registration) date,
    i.e. from-created-date = today - N. This tracks "newly indexed in Crossref"
    rather than the print-issue date, so it fits a daily new-arrivals briefing.
  - A `mailto` is sent to use Crossref's faster "polite pool".
  - stdlib only.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.parse
import urllib.request
import html as htmllib
from datetime import date, timedelta

# Force UTF-8 stdout on Windows (default cp949 / cp1252 will reject many chars).
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "https://api.crossref.org/works"
# Polite-pool contact; override with --mailto.
DEFAULT_MAILTO = "imaging.snu@gmail.com"
# Only request the fields we map, to keep responses small.
SELECT = "DOI,title,author,container-title,abstract,published,issued,created,subject,URL"


def strip_jats(s: str) -> str:
    """Crossref abstracts are JATS XML; reduce to clean plain text."""
    if not s:
        return ""
    # Drop the redundant "Abstract" title element content marker, then tags.
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def build_url(query: str, issn: str, from_date: str, until_date: str, rows: int, mailto: str) -> str:
    # Filter by Crossref *created* date (when the DOI was first registered) instead of
    # publication date: it tracks "newly appeared in Crossref" and avoids the print-issue
    # date lag, which fits a daily "new arrivals" briefing. until-created-date also drops
    # the future-dated metadata records Crossref carries.
    filters = [
        "type:journal-article",
        f"from-created-date:{from_date}",
        f"until-created-date:{until_date}",
    ]
    if issn:
        filters.append(f"issn:{issn}")
    params = {
        "filter": ",".join(filters),
        "rows": str(rows),
        "select": SELECT,
        "order": "desc",
        "mailto": mailto,
    }
    if query:
        # Keyword mode: rank by query relevance (sorting by date would drown the query out).
        params["query.bibliographic"] = query
        params["sort"] = "relevance"
    else:
        # Venue-only mode: newest registered first.
        params["sort"] = "created"
    return API + "?" + urllib.parse.urlencode(params)


def fetch_json(url: str, mailto: str) -> dict:
    ua = f"paper-daily-summary/1.0 (https://github.com/IIL-SNU/paper-daily-summary; mailto:{mailto})"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _date(item: dict, *keys: str) -> str:
    for key in keys:
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            y = parts[0] + [1, 1]  # pad missing month/day
            return f"{y[0]:04d}-{y[1]:02d}-{y[2]:02d}"
    return ""


def pub_date(item: dict) -> str:
    return _date(item, "published", "issued", "published-online", "published-print")


def to_paper(item: dict) -> dict:
    doi = item.get("DOI", "")
    titles = item.get("title") or [""]
    title = strip_jats(titles[0]) if titles else ""
    authors = []
    for a in item.get("author") or []:
        name = " ".join(p for p in [a.get("given", ""), a.get("family", "")] if p).strip()
        if not name:
            name = a.get("name", "")
        if name:
            authors.append(name)
    containers = item.get("container-title") or [""]
    journal = containers[0] if containers else ""
    subjects = "; ".join(item.get("subject") or [])
    return {
        "source": "crossref",
        "doi": doi,
        "id": f"doi:{doi}" if doi else "",
        "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        "title": title,
        "authors": authors,
        "first_author": authors[0] if authors else "",
        "journal": journal,
        "subjects": subjects,
        "primary_cat": "",          # journals have no arXiv primary category
        "section": "new",           # uniform with arXiv /new items
        "abstract": strip_jats(item.get("abstract", "")),
        "published": pub_date(item),
        "created": _date(item, "created"),   # Crossref registration date (crawl criterion)
    }


def main():
    ap = argparse.ArgumentParser(description="Fetch recent journal articles via Crossref.")
    ap.add_argument("--query", action="append", default=[], help="Keyword query (query.bibliographic); repeatable — each runs separately and results merge.")
    ap.add_argument("--issn", action="append", default=[], help="Venue ISSN; repeatable.")
    ap.add_argument("--days", type=int, default=7, help="Look back N days by Crossref created (registration) date.")
    ap.add_argument("--rows", type=int, default=60, help="Max results per request.")
    ap.add_argument("--mailto", default=DEFAULT_MAILTO, help="Crossref polite-pool contact.")
    args = ap.parse_args()

    if not args.query and not args.issn:
        ap.error("provide at least one of --query or --issn")

    until_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=args.days)).isoformat()
    query_targets = args.query or [""]  # "" => no keyword (ISSN-only)
    issn_targets = args.issn or [""]    # "" => no ISSN filter (keyword-only)

    by_id: dict[str, dict] = {}
    for q in query_targets:
        for issn in issn_targets:
            url = build_url(q, issn, from_date, until_date, args.rows, args.mailto)
            try:
                data = fetch_json(url, args.mailto)
            except Exception as e:  # one query/ISSN hiccup shouldn't kill the rest
                print(f"[fetch_crossref] WARN: request failed for query={q!r} issn={issn or 'ANY'}: {e}", file=sys.stderr)
                continue
            for item in data.get("message", {}).get("items", []):
                paper = to_paper(item)
                key = paper["id"] or paper["url"] or paper["title"]
                by_id.setdefault(key, paper)

    papers = list(by_id.values())
    print(json.dumps(papers, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
