#!/usr/bin/env python3
"""Enrich papers with OpenAlex, and optionally fetch recent works as a source.

OpenAlex (https://openalex.org) aggregates Crossref + arXiv + PubMed and adds
disambiguated authors, concept tags, citation counts, and abstracts. We use it as
an ENRICHMENT layer on top of the arXiv + Crossref collection — Crossref stays the
primary daily source (freshest at registration time); OpenAlex adds signal:

  - cited_by_count -> objective importance signal for must-read / Tier ranking
  - concepts       -> secondary subject signal for ROI bucket classification
  - abstract       -> backfills the ~50% of Crossref records that ship no abstract
                      (reconstructed from OpenAlex's inverted index)

Keyless REST API; a `mailto` uses the polite pool. stdlib only.

Modes:
  enrich : read a JSON array of papers (or classify.py's classified.json) from a
           file/stdin; for each paper with a DOI, attach cited_by_count + concepts
           and backfill a missing abstract. Writes the same structure back.
               python scripts/fetch_openalex.py enrich out/journal_new.json > out/journal_enriched.json
               python scripts/fetch_crossref.py ... | python scripts/fetch_openalex.py enrich -

  works  : fetch recent works by created-date + keyword, in the SAME schema as
           fetch_crossref.py (+ enrichment fields), as a supplementary journal
           source (source="openalex", badge OAX). Independent of arXiv.
               python scripts/fetch_openalex.py works --query "computational imaging" --days 1 > out/openalex_new.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "https://api.openalex.org/works"
DEFAULT_MAILTO = "imaging.snu@gmail.com"
# OpenAlex caps OR-filter values per request; keep DOI batches under it.
DOI_BATCH = 40


def fetch_json(url: str, mailto: str, retries: int = 4) -> dict:
    ua = f"paper-daily-summary/1.0 (https://github.com/IIL-SNU/paper-daily-summary; mailto:{mailto})"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            # OpenAlex throttles bursts with 429 (and 503 under load); back off and retry.
            if e.code in (429, 503) and attempt < retries:
                time.sleep(2 ** attempt)  # 1, 2, 4, 8s
                continue
            raise


def reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex ships abstracts as an inverted index {word: [positions]} (licensing).
    Rebuild the linear text."""
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def bare_doi(doi: str) -> str:
    if not doi:
        return ""
    return doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip().lower()


def concept_names(work: dict, limit: int = 5, min_score: float = 0.3) -> list[str]:
    out = []
    for c in work.get("concepts") or []:
        if c.get("score", 0) >= min_score and c.get("display_name"):
            out.append(c["display_name"])
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- works mode

def work_to_paper(w: dict) -> dict:
    doi = bare_doi(w.get("doi") or "")
    title = w.get("title") or w.get("display_name") or ""
    authors = [
        a["author"]["display_name"]
        for a in (w.get("authorships") or [])
        if a.get("author") and a["author"].get("display_name")
    ]
    src = ((w.get("primary_location") or {}).get("source") or {})
    concepts = concept_names(w)
    return {
        "source": "openalex",
        "doi": doi,
        "id": f"doi:{doi}" if doi else (w.get("id") or ""),
        "url": (w.get("doi") or w.get("id") or ""),
        "title": title,
        "authors": authors,
        "first_author": authors[0] if authors else "",
        "journal": src.get("display_name") or "",
        # Fold concept names into subjects so classify.py's keyword match can use them.
        "subjects": "; ".join(concepts),
        "primary_cat": "",
        "section": "new",
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "published": w.get("publication_date") or "",
        "created": (w.get("created_date") or "")[:10],
        "cited_by_count": w.get("cited_by_count", 0),
        "concepts": concepts,
    }


def run_works(args) -> None:
    until = date.today().isoformat()
    since = (date.today() - timedelta(days=args.days)).isoformat()
    select = ",".join([
        "id", "doi", "title", "display_name", "authorships", "primary_location",
        "concepts", "abstract_inverted_index", "publication_date", "created_date",
        "cited_by_count", "type",
    ])
    by_id: dict[str, dict] = {}
    for q in (args.query or [""]):
        # Filter by publication_date, not created_date: OpenAlex rate-limits the
        # created_date filter hard (HTTP 429), and publication_date is the more
        # meaningful "recent work" window anyway.
        filters = [
            f"from_publication_date:{since}",
            f"to_publication_date:{until}",
            "primary_location.source.type:journal",  # journals only (avoid arXiv overlap)
        ]
        params = {
            "filter": ",".join(filters),
            "select": select,
            "per-page": str(args.rows),
            "mailto": args.mailto,
        }
        if q:
            params["search"] = q  # relevance-ranked full-text-ish search
        else:
            params["sort"] = "publication_date:desc"
        url = API + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url, args.mailto)
        except Exception as e:
            print(f"[fetch_openalex] WARN: works request failed for query={q!r}: {e}", file=sys.stderr)
            continue
        for w in data.get("results", []):
            paper = work_to_paper(w)
            key = paper["id"] or paper["url"] or paper["title"]
            by_id.setdefault(key, paper)
    print(json.dumps(list(by_id.values()), ensure_ascii=False, indent=1))


# --------------------------------------------------------------- enrich mode

def collect_papers(obj) -> list[dict]:
    """Accept either a flat list of papers or classify.py's classified.json
    ({buckets: {name: {papers: [...]}}}); return the list of paper dicts in place."""
    if isinstance(obj, list):
        return [p for p in obj if isinstance(p, dict)]
    papers: list[dict] = []
    buckets = (obj or {}).get("buckets") if isinstance(obj, dict) else None
    if isinstance(buckets, dict):
        for b in buckets.values():
            for p in (b or {}).get("papers", []):
                if isinstance(p, dict):
                    papers.append(p)
    return papers


def run_enrich(args) -> None:
    text = (sys.stdin if args.input in ("-", None) else open(args.input, encoding="utf-8")).read()
    obj = json.loads(text)
    papers = collect_papers(obj)

    # Map bare DOI -> paper(s) to enrich.
    want: dict[str, list[dict]] = {}
    for p in papers:
        d = bare_doi(p.get("doi") or (p.get("id", "")[4:] if str(p.get("id", "")).startswith("doi:") else ""))
        if d:
            want.setdefault(d, []).append(p)

    dois = list(want)
    select = "doi,cited_by_count,concepts,abstract_inverted_index"
    enriched = 0
    for i in range(0, len(dois), DOI_BATCH):
        batch = dois[i:i + DOI_BATCH]
        params = {
            "filter": "doi:" + "|".join(batch),
            "select": select,
            "per-page": str(len(batch)),
            "mailto": args.mailto,
        }
        url = API + "?" + urllib.parse.urlencode(params, safe="|:")
        try:
            data = fetch_json(url, args.mailto)
        except Exception as e:
            print(f"[fetch_openalex] WARN: enrich batch failed: {e}", file=sys.stderr)
            continue
        for w in data.get("results", []):
            d = bare_doi(w.get("doi") or "")
            for p in want.get(d, []):
                p["cited_by_count"] = w.get("cited_by_count", 0)
                cs = concept_names(w)
                if cs:
                    p["concepts"] = cs
                    # Make concepts visible to classify.py's keyword matcher.
                    p["subjects"] = ("; ".join(filter(None, [p.get("subjects", ""), "; ".join(cs)]))).strip("; ")
                if not (p.get("abstract") or "").strip():
                    ab = reconstruct_abstract(w.get("abstract_inverted_index"))
                    if ab:
                        p["abstract"] = ab
                enriched += 1

    print(f"[fetch_openalex] enriched {enriched}/{len(papers)} papers ({len(dois)} DOIs)", file=sys.stderr)
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenAlex enrichment + supplementary source.")
    sub = ap.add_subparsers(dest="mode", required=True)

    e = sub.add_parser("enrich", help="Attach cited_by_count/concepts and backfill abstracts.")
    e.add_argument("input", nargs="?", default="-", help="papers JSON file or '-' for stdin")
    e.add_argument("--mailto", default=DEFAULT_MAILTO)

    w = sub.add_parser("works", help="Fetch recent journal works (supplementary source).")
    w.add_argument("--query", action="append", default=[], help="Keyword query; repeatable.")
    w.add_argument("--days", type=int, default=1, help="Look back N days by publication_date.")
    w.add_argument("--rows", type=int, default=50, help="Max results per query (per-page, <=200).")
    w.add_argument("--mailto", default=DEFAULT_MAILTO)

    args = ap.parse_args()
    if args.mode == "works":
        run_works(args)
    else:
        run_enrich(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
