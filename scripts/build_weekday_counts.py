#!/usr/bin/env python3
"""Build homepage daily /new counts from repo-local trends metadata only.

Reads each committed trends/<date>.json `daily_new_counts.by_cat` and emits a
date-by-date time series for the homepage chart. Does not fetch arXiv — this is
a view of data already collected for this repository. Weekend reports are
skipped so a reused Friday listing is not shown as weekend submission volume.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
from pathlib import Path


if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def is_weekend(date: str) -> bool:
    return dt.date.fromisoformat(date).weekday() >= 5


def collect_from_trends(root: Path):
    entries = {}
    for path in sorted((root / "trends").glob("20??-??-??.json")):
        match = DATE_RE.search(path.name)
        if not match:
            continue
        date = match.group(1)
        if is_weekend(date):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        counts = payload.get("daily_new_counts") or {}
        by_cat = counts.get("by_cat")
        if not isinstance(by_cat, dict):
            continue
        by_cat = {k: int(v or 0) for k, v in by_cat.items()}
        entries[date] = {
            "date": date,
            "total": sum(by_cat.values()),
            "by_cat": by_cat,
            "scope": str(counts.get("scope") or "new+cross"),
            "source": path.relative_to(root).as_posix(),
        }
    return entries


def build(root: Path):
    entries = collect_from_trends(root)
    daily = []
    for date, row in sorted(entries.items()):
        out = dict(row)
        out["weekday"] = dt.date.fromisoformat(date).strftime("%a")
        daily.append(out)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "repo-local saved daily /new metadata only; no external arXiv fetch",
        "note": (
            "Per-category /new counts include cross-listed entries when recorded as "
            "new+cross. Replacement/update-only entries are excluded. Weekend reports skipped."
        ),
        "windows": [
            {"label": "1개월", "days": 31},
            {"label": "3개월", "days": 92},
            {"label": "6개월", "days": 183},
            {"label": "1년", "days": 366},
            {"label": "2년", "days": 731},
            {"label": "3년", "days": 1096},
        ],
        "daily": daily,
    }


def main() -> int:
    root = Path.cwd()
    output = root / "stats" / "weekday_counts.json"
    payload = build(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}: {len(payload['daily'])} repo-local daily count rows")
    for row in payload["daily"]:
        cats = " ".join(f"{k}={v}" for k, v in row["by_cat"].items())
        print(f"  {row['date']} {row['weekday']}  total={row['total']}  ({cats})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
