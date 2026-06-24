#!/usr/bin/env python3
"""Classify today's /new papers into ROI buckets by keyword match.

Reads one JSON file per tracked arXiv category (out/<cat>_new.json) plus an
optional journal source (out/journal_new.json from fetch_crossref.py), merges
and dedupes them, assigns each paper to its strongest-matching ROI bucket, and
prints a grouped summary as JSON.
"""
import io
import json
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# arXiv categories this lab tracks. Order = display / badge priority.
CATEGORIES = ["cs.LG", "cs.CV", "cs.AI", "eess.IV", "eess.SP"]
# Short labels used as per-paper badges.
CAT_BADGE = {
    "cs.LG": "LG",
    "cs.CV": "CV",
    "cs.AI": "AI",
    "eess.IV": "IV",
    "eess.SP": "SP",
}
JOURNAL_FILE = "out/journal_new.json"
# Optional OpenAlex supplementary source (fetch_openalex.py works mode).
OPENALEX_FILE = "out/openalex_new.json"

# Lab ROI buckets for a computational optical imaging group (Imaging Intelligence Lab).
# Derived from the group's publications + tracked literature: Fourier ptychography,
# lensless/computational cameras, phase imaging, holography, meta-optics, light-field,
# tomography, virtual staining — plus the ML methods consumed from arXiv cs.*.
# Specific optics buckets are ordered first so they win keyword ties over generic ML terms.
# (Tune the keyword lists to your group's focus.)
BUCKETS = [
    ("Fourier Ptychography/Microscopy", [
        "fourier ptychography", "ptychograph", "ptychographic", "computational microscopy",
        "aperture synthesis", "synthetic aperture", "coded illumination",
        "illumination multiplexing", "high-resolution microscopy", "quantitative microscopy",
    ]),
    ("Lensless/Coded Imaging", [
        "lensless", "coded aperture", "point spread function", "psf engineering",
        "diffuser", "mask-based", "single-shot imaging", "computational camera",
        "coded exposure", "snapshot imaging",
    ]),
    ("Phase Imaging/Holography", [
        "quantitative phase", "phase retrieval", "phase imaging", "phase microscopy",
        "holography", "holographic", "computer-generated holography", "digital holography",
        "wavefront", "interferometry", "angular spectrum", "diffraction model",
    ]),
    ("Meta-Optics/Diffractive", [
        "metasurface", "metalens", "meta-optics", "metaoptics", "diffractive optics",
        "nanophotonic", "flat optics", "inverse lithography", "freeform optics",
        "optical inverse design", "diffractive neural network",
    ]),
    ("Light-Field/Novel Sensors", [
        "light field", "light-field", "plenoptic", "event camera", "event-based",
        "neuromorphic", "spike camera", "integral imaging", "light-field display",
    ]),
    ("Tomography/3D Imaging", [
        "tomography", "tomographic", "optical diffraction tomography", "diffraction tomography",
        "volumetric imaging", "3d reconstruction", "gaussian splatting", "nerf",
        "neural radiance", "light-field microscopy", "refractive index tomography",
    ]),
    ("Virtual Staining/Pathology", [
        "virtual staining", "digital pathology", "histopathology", "label-free",
        "stain", "whole slide", "tissue imaging", "cytology", "h&e",
    ]),
    ("Reconstruction/Inverse Problems", [
        "image reconstruction", "inverse problem", "deep unfolding", "unrolling", "unrolled",
        "plug-and-play", "compressed sensing", "deconvolution", "computational imaging",
        "model-based", "regularization", "physics-informed",
    ]),
    ("Deep Learning Methods", [
        "diffusion model", "generative model", "neural network", "deep learning",
        "self-supervised", "foundation model", "transformer", "implicit neural representation",
        "super-resolution", "denoising", "image restoration", "representation learning",
    ]),
]


def assign_bucket(title: str, abstract: str, subjects: str) -> str:
    """Return the strongest-matching bucket for a paper, or empty string if none."""
    text = (title + " " + abstract + " " + subjects).lower()
    best = ""
    best_hits = 0
    for bucket, kws in BUCKETS:
        hits = sum(1 for kw in kws if kw in text)
        if hits > best_hits:
            best_hits = hits
            best = bucket
    return best if best_hits > 0 else ""


def primary_badge(paper) -> str:
    """Short source label: a tracked arXiv category, JNL for journals, else '?'."""
    if paper.get("source") == "crossref":
        return "JNL"
    if paper.get("source") == "openalex":
        return "OAX"
    primary = paper.get("primary_cat", "")
    if primary in CAT_BADGE:
        return CAT_BADGE[primary]
    subjects = paper.get("subjects", "")
    for cat, badge in CAT_BADGE.items():
        if cat in subjects:
            return badge
    return primary or "?"


def paper_id(paper) -> str:
    """Unified dedupe key across arXiv (arxiv_id) and journals (id/doi)."""
    return paper.get("arxiv_id") or paper.get("id") or paper.get("doi") or ""


def load_sources():
    """Load every tracked category file that exists, plus the journal file."""
    papers = []
    for cat in CATEGORIES:
        path = f"out/{cat}_new.json"
        if os.path.exists(path):
            papers.extend(json.load(open(path, encoding="utf-8")))
        else:
            print(f"[classify] note: {path} missing, skipping", file=sys.stderr)
    for path in (JOURNAL_FILE, OPENALEX_FILE):
        if os.path.exists(path):
            papers.extend(json.load(open(path, encoding="utf-8")))
    return papers


def main():
    raw = load_sources()
    # Merge and dedupe on the unified id, dropping replacements and id-less rows.
    by_id = {}
    for p in raw:
        if p.get("section") == "replace":
            continue
        pid = paper_id(p)
        if not pid:
            continue
        by_id.setdefault(pid, p)
    papers = list(by_id.values())

    # Classify
    for p in papers:
        p["bucket"] = assign_bucket(p.get("title", ""), p.get("abstract", ""), p.get("subjects", ""))
        p["badge"] = primary_badge(p)

    # Group
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in papers:
        if p["bucket"]:
            grouped[p["bucket"]].append(p)

    # Output summary
    order = [b for b, _ in BUCKETS]
    result = {
        "total": len(papers),
        "selected": sum(len(grouped[b]) for b in order),
        "categories": CATEGORIES,
        "buckets": {},
    }
    for b in order:
        items = grouped[b]
        by_cat = {}
        for p in items:
            by_cat[p["badge"]] = by_cat.get(p["badge"], 0) + 1
        result["buckets"][b] = {
            "total": len(items),
            "by_badge": by_cat,   # e.g. {"CV": 4, "LG": 2, "IV": 1, "JNL": 1}
            "papers": items,
        }
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
