#!/usr/bin/env python3
"""Fetch and parse arxiv /new or /pastweek pages.

WebFetch summarizes long pages through an AI model and truncates at ~40 papers.
This script bypasses that by downloading raw HTML and parsing with stdlib only.

Usage (output filename convention: out/<cat>_new.json):
    python scripts/fetch_arxiv.py new cs.LG > out/cs.LG_new.json
    python scripts/fetch_arxiv.py new eess.IV > out/eess.IV_new.json
    python scripts/fetch_arxiv.py pastweek cs.LG > out/cs.LG_pastweek.json

Output: JSON array. Each item has arxiv_id, title, authors, subjects, abstract
(abstract only for /new), section ("new" | "cross"), primary_cat.
In `new` mode, replacements (updates to older papers) are dropped so only
genuinely recent submissions/cross-lists remain.
"""
import io
import json
import re
import sys
import urllib.request
import html as htmllib

# Force UTF-8 stdout on Windows (default cp949 / cp1252 will reject many chars).
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


UA = "Mozilla/5.0 (paper-daily-summary helper)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# Each paper block on /list pages starts with a list-identifier and ends before the next one.
# Section headers look like <h3>...New submissions...</h3>, <h3>...Cross-lists...</h3>,
# <h3>...Replacements...</h3>.

SECTION_RE = re.compile(r"<h3[^>]*>([^<]+)</h3>", re.I)
ID_RE = re.compile(r'href\s*=\s*["\']/abs/([^"\']+)["\']', re.I)
TITLE_RE = re.compile(
    r"list-title[^>]*>\s*<span[^>]*>Title:</span>\s*(.*?)\s*</div>", re.S
)
AUTHORS_RE = re.compile(r"list-authors[^>]*>(.*?)</div>", re.S)
SUBJECTS_RE = re.compile(
    r"list-subjects[^>]*>\s*<span[^>]*>Subjects:</span>\s*(.*?)\s*</div>", re.S
)
ABS_RE = re.compile(r"<p class=['\"]mathjax['\"][^>]*>(.*?)</p>", re.S)


def classify_section(title: str) -> str:
    t = title.lower()
    if "cross" in t:
        return "cross"
    if "replac" in t:
        return "replace"
    if "new submission" in t:
        return "new"
    # /pastweek pages use date-formatted h3 like "Fri, 24 Apr 2026 (showing ...)".
    # Treat as a new-listing block for parser purposes.
    if re.match(r"^(mon|tue|wed|thu|fri|sat|sun),\s+\d", t):
        return "new"
    return "other"


def split_by_section(html: str):
    """Yield (section_key, block_html) pairs."""
    positions = [(m.start(), classify_section(m.group(1))) for m in SECTION_RE.finditer(html)]
    if not positions:
        yield "new", html
        return
    for i, (pos, section) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(html)
        yield section, html[pos:end]


def parse_papers(html: str, include_abstract: bool):
    """Parse all papers from the page, preserving section labels."""
    out = []
    for section, block in split_by_section(html):
        if section == "other":
            # Page banner h3 like "Showing new listings for ..." — skip.
            continue
        # Split block into paper chunks on list-identifier occurrences.
        chunks = re.split(r"""<dt>\s*<a\s+name=["']item""", block)
        for chunk in chunks[1:]:
            mid = ID_RE.search(chunk)
            if not mid:
                continue
            arxiv_id = mid.group(1)
            mtitle = TITLE_RE.search(chunk)
            mauthors = AUTHORS_RE.search(chunk)
            msubj = SUBJECTS_RE.search(chunk)
            title = strip_tags(mtitle.group(1)) if mtitle else ""
            authors_raw = mauthors.group(1) if mauthors else ""
            # Strip "Authors:" prefix plus tags.
            authors_txt = re.sub(r"<span[^>]*>Authors:</span>\s*", "", authors_raw, flags=re.I)
            authors_list = [strip_tags(a) for a in re.findall(r"<a[^>]*>(.*?)</a>", authors_txt)]
            subjects = strip_tags(msubj.group(1)) if msubj else ""
            primary = ""
            m = re.search(r"([a-z\-]+\.[A-Z]{2})", subjects)
            if m:
                primary = m.group(1)

            item = {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors_list,
                "first_author": authors_list[0] if authors_list else "",
                "subjects": subjects,
                "primary_cat": primary,
                "section": section,
            }
            if include_abstract:
                mabs = ABS_RE.search(chunk)
                item["abstract"] = strip_tags(mabs.group(1)) if mabs else ""
            out.append(item)
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    mode = sys.argv[1]  # "new" or "pastweek"
    cat = sys.argv[2]   # "cs.CV" etc.
    if mode == "new":
        url = f"https://arxiv.org/list/{cat}/new"
        include_abs = True
    elif mode == "pastweek":
        url = f"https://arxiv.org/list/{cat}/pastweek?skip=0&show=2000"
        include_abs = False
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(2)

    html = fetch(url)
    papers = parse_papers(html, include_abstract=include_abs)
    if mode == "new":
        # /new is the latest announcement. Keep genuinely new submissions and
        # cross-lists (both carry current arxiv IDs), but drop replacements —
        # those are updates to OLDER papers and carry old IDs, so they are not
        # "submitted within the last week".
        papers = [p for p in papers if p.get("section") != "replace"]
    print(json.dumps(papers, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
