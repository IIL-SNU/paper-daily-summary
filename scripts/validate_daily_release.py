#!/usr/bin/env python3
"""Validate daily arXiv briefing artifacts before commit/push."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AssertionError(f"invalid JSON: {path.relative_to(ROOT)} ({exc})")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def daily_dates() -> list[str]:
    out = []
    for path in (ROOT / "posts").glob("20??-??-??.html"):
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", path.stem):
            out.append(path.stem)
    return sorted(out)


def previous_date(date: str) -> str | None:
    dates = [d for d in daily_dates() if d < date]
    return dates[-1] if dates else None


def cluster_titles(payload: dict) -> list[str]:
    rows = payload.get("clusters")
    if not isinstance(rows, list):
        rows = payload.get("insights")
    if not isinstance(rows, list):
        return []
    titles = []
    for row in rows:
        if isinstance(row, dict):
            title = row.get("cluster") or row.get("title")
            if title:
                titles.append(str(title).strip())
    return titles


def paper_ids(payload: dict) -> set[str]:
    ids: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            m = re.search(r"arxiv\.org/abs/([0-9.]+)", value)
            if m:
                ids.add(m.group(1))

    walk(payload)
    return ids


def validate(date: str) -> list[str]:
    warnings: list[str] = []
    post_path = ROOT / "posts" / f"{date}.html"
    trends_path = ROOT / "trends" / f"{date}.json"
    insights_path = ROOT / "insights" / f"{date}.json"
    benchmarks_path = ROOT / "benchmarks" / f"{date}.json"
    feed_path = ROOT / "feed.xml"
    stats_path = ROOT / "stats" / "weekday_counts.json"

    for path in [post_path, trends_path, insights_path, benchmarks_path, feed_path]:
        require(path.exists(), f"missing required artifact: {path.relative_to(ROOT)}")

    trends = load_json(trends_path)
    insights = load_json(insights_path)
    load_json(benchmarks_path)
    html = post_path.read_text(encoding="utf-8", errors="replace")
    feed = feed_path.read_text(encoding="utf-8", errors="replace")

    require(trends.get("date") == date, f"trends.date mismatch: {trends.get('date')} != {date}")
    require(trends.get("source_listing_date") == date, "trends.source_listing_date must match date")
    require(trends.get("source_mode") in {"new", "pastweek-date-section", "journal-only"}, "trends.source_mode must be new, pastweek-date-section, or journal-only")
    counts = trends.get("daily_new_counts") or {}
    require(counts.get("scope") == "new+cross; replacements excluded", "daily_new_counts.scope must exclude replacements")
    require(isinstance(counts.get("by_cat"), dict) and counts["by_cat"], "daily_new_counts.by_cat must be a non-empty dict")
    require(all(isinstance(v, int) for v in counts["by_cat"].values()), "daily_new_counts.by_cat values must be integers")

    totals = trends.get("totals") or {}
    require(isinstance(totals.get("total_scanned"), int), "totals.total_scanned must be integer")
    require(isinstance(totals.get("selected"), int), "totals.selected must be integer")
    require(totals["total_scanned"] >= totals["selected"] >= 0, "invalid selected/total_scanned relation")

    require("<h1" in html and date in html, "post HTML must contain h1 and date")
    require("Cluster</th>" in html and "대표 논문" in html and "왜 중요?" in html, "cluster table headers missing")
    require(f"posts/{date}.html" in feed, "feed.xml missing post link")

    titles = cluster_titles(insights)
    require(len(titles) >= 3, "at least three daily cluster/insight titles required")
    require(len(set(titles)) == len(titles), "duplicate cluster titles inside same day")

    prev = previous_date(date)
    if prev and (ROOT / "insights" / f"{prev}.json").exists() and (ROOT / "trends" / f"{prev}.json").exists():
        prev_insights = load_json(ROOT / "insights" / f"{prev}.json")
        overlap = set(titles) & set(cluster_titles(prev_insights))
        require(len(overlap) < 4, f"too many cluster titles reused from {prev}: {sorted(overlap)}")

        prev_trends = load_json(ROOT / "trends" / f"{prev}.json")
        same_counts = (prev_trends.get("daily_new_counts") or {}) == counts
        same_totals = (prev_trends.get("totals") or {}).get("total_scanned") == totals.get("total_scanned") and (
            prev_trends.get("totals") or {}
        ).get("selected") == totals.get("selected")
        same_ids = paper_ids(prev_insights) == paper_ids(insights)
        require(not (same_counts and same_totals and same_ids), f"daily source appears identical to previous daily {prev}")

    for idx, row in enumerate(insights.get("clusters", [])[:6], start=1):
        papers = row.get("papers") if isinstance(row, dict) else None
        require(isinstance(papers, list) and len(papers) >= 2, f"cluster {idx} needs at least two representative papers")
        why = str(row.get("why") or "")
        require(len(why) >= 80, f"cluster {idx} why is too short")

    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    try:
        warnings = validate(args.date)
    except AssertionError as exc:
        print(f"[validate_daily_release] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[validate_daily_release] PASS: {args.date}")
    for warning in warnings:
        print(f"[validate_daily_release] WARN: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
