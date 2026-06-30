#!/usr/bin/env python3
"""Safety net: make sure index.html links every post.

The landing page is hand-authored by the agent, so a run can silently forget to
add a new daily/weekly (it happened: 2026-06-29 was published but not linked).
This reconciles index.html against posts/: any posts/*.html not already linked
gets a fallback entry (date label + title/summary extracted from the post),
inserted in newest-first order. Curated entries are preserved verbatim; only the
missing ones are added, and only when something is actually missing (no churn).

Run after the agent generates index.html, before inject_dark.py:
    python scripts/reconcile_index.py
"""
import re, glob, os, datetime
import html as htmllib

INDEX = "index.html"
KOR_DOW = ["월", "화", "수", "목", "금", "토", "일"]
ENTRY_RE = re.compile(r'<a class="entry[^"]*" href="posts/([^"]+)">.*?</a>', re.S)


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def daily_label(d: datetime.date) -> str:
    return f"{d.isoformat()} ({KOR_DOW[d.weekday()]})"


def weekly_label(d: datetime.date) -> str:
    # Weekly is published Monday D, reviewing the prior week (Mon D-7 .. Fri D-3).
    wk = d - datetime.timedelta(days=7)
    fri = d - datetime.timedelta(days=3)
    iso = wk.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d} · {wk.strftime('%m-%d')} ~ {fri.strftime('%m-%d')}"


def extract_summary(doc: str, n: int = 300) -> str:
    for pat in (r"결론[^<]*</h2>\s*<[^>]*>(.*?)</(?:div|p)",
                r"Executive Summary[^<]*</h2>\s*<[^>]*>(.*?)</(?:div|p)",
                r"class=thesis[^>]*>(.*?)</div",
                r"주간 동향.*?</h2>\s*<p[^>]*>(.*?)</p>"):
        m = re.search(pat, doc, re.S)
        if m:
            s = strip_tags(m.group(1))
            if s:
                return s[:n]
    return ""


def build_entry(name: str, d: datetime.date, weekly: bool, title: str, summary: str) -> str:
    cls = "entry wk" if weekly else "entry"
    tag = '<span class="tag w">Weekly</span>' if weekly else '<span class="tag">Daily</span>'
    label = weekly_label(d) if weekly else daily_label(d)
    return (f'<a class="{cls}" href="posts/{name}"><div class="d">{label}{tag}</div>'
            f'<div class="t">{htmllib.escape(title)}</div>'
            f'<div class="s">{htmllib.escape(summary)}</div></a>')


def main() -> int:
    h = open(INDEX, encoding="utf-8").read()

    entries = []   # (date, weekly, blob)
    linked = set()
    for m in ENTRY_RE.finditer(h):
        name = m.group(1)
        linked.add(name)
        try:
            d = datetime.date.fromisoformat(name[:10])
        except ValueError:
            continue
        entries.append((d, "-weekly" in name, m.group(0)))

    added = []
    for path in sorted(glob.glob("posts/*.html")):
        name = os.path.basename(path)
        if not re.match(r"\d{4}-\d{2}-\d{2}", name) or name in linked:
            continue
        d = datetime.date.fromisoformat(name[:10])
        weekly = "-weekly" in name
        doc = open(path, encoding="utf-8").read()
        title = "🗓 주간 회고" if weekly else f"{d.isoformat()} 브리핑"
        entries.append((d, weekly, build_entry(name, d, weekly, title, extract_summary(doc))))
        added.append(name)

    if not added:
        print("reconcile_index: nothing missing")
        return 0

    # Newest first; for the same date, weekly above daily.
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
    block = "\n\n".join(e[2] for e in entries)
    first = h.find('<a class="entry')
    last = h.rfind("</a>") + len("</a>")
    open(INDEX, "w", encoding="utf-8").write(h[:first] + block + h[last:])
    print(f"reconcile_index: added {len(added)} missing entr(ies): {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
