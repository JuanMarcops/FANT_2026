#!/usr/bin/env python3
"""Build the conference Book of Contents from a committed CSV file.

Produces a static website (index.html) and a PDF (book_of_contents.pdf)
in the output directory.

Usage:
    python scripts/build.py
        Use the CSV path from config.yml (input.csv_path).
    python scripts/build.py --csv data/responses.sample.csv
        Override the CSV path (handy for testing with sample data).
    python scripts/build.py --out site
        Choose the output directory (default: site).

All conference-specific settings live in config.yml, not here.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"


def load_config() -> dict:
    with open(ROOT / "config.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_csv(path: Path, colmap: dict) -> list[dict]:
    """Read the exported CSV into canonical submission dicts.

    `utf-8-sig` strips the BOM that Google sometimes prepends.
    Empty mappings ("") simply yield empty fields.
    """
    submissions = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            title = rec.get(colmap.get("title", ""), "").strip()
            if not title:
                continue  # skip blank / malformed rows
            submissions.append(
                {
                    "authors": rec.get(colmap.get("authors", ""), "").strip(),
                    "title": title,
                    "abstract": rec.get(colmap.get("abstract", ""), "").strip(),
                    "track": rec.get(colmap.get("track", ""), "").strip()
                    or "Weitere Beiträge",
                    "keywords": rec.get(colmap.get("keywords", ""), "").strip(),
                }
            )
    return submissions


def group_by_session(submissions: list[dict], cfg: dict) -> list[dict]:
    """Return ordered list of {"track": str, "entries": [...]} blocks."""
    order = cfg.get("session_order") or []
    by_track: dict[str, list[dict]] = {}
    for s in submissions:
        by_track.setdefault(s["track"], []).append(s)

    # Sort entries within a track by title for stable, reproducible output.
    for entries in by_track.values():
        entries.sort(key=lambda e: e["title"].lower())

    ordered = [t for t in order if t in by_track]
    rest = sorted(t for t in by_track if t not in order)
    return [{"track": t, "entries": by_track[t]} for t in ordered + rest]


def render(cfg: dict, sessions: list[dict], out_dir: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )
    total = sum(len(s["entries"]) for s in sessions)
    ctx = {
        "conf": cfg["conference"],
        "sessions": sessions,
        "total": total,
        "generated": date.today().isoformat(),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(
        env.get_template("boc_web.html.j2").render(**ctx), encoding="utf-8"
    )

    # PDF: render print-oriented HTML, then convert with WeasyPrint.
    pdf_html = env.get_template("boc_pdf.html.j2").render(**ctx)
    HTML(string=pdf_html, base_url=str(TEMPLATES)).write_pdf(
        str(out_dir / "book_of_contents.pdf")
    )
    print(f"Rendered {total} entries -> {out_dir}/index.html + book_of_contents.pdf")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="override the CSV path from config.yml")
    p.add_argument("--out", default="site", help="output directory (default: site)")
    args = p.parse_args()

    cfg = load_config()
    csv_path = ROOT / (args.csv or cfg["input"]["csv_path"])
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    submissions = read_csv(csv_path, cfg["input"]["columns"])
    if not submissions:
        print("No submissions found in CSV.", file=sys.stderr)
        return 1

    sessions = group_by_session(submissions, cfg)
    render(cfg, sessions, ROOT / args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
