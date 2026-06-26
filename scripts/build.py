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
import re
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"


def load_config() -> dict:
    with open(ROOT / "config.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def normalize_header(label: str) -> str:
    if label is None:
        return ""
    normalized = unicodedata.normalize("NFKC", label.strip().lower())
    normalized = (
        normalized.replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("ß", "ss")
        .replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
        .replace("‘", "'")
    )
    return " ".join(normalized.split())


def normalize_column_spec(value):
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if value:
        return [str(value)]
    return []


def build_header_index(header_row: list[str]) -> dict[str, list[int]]:
    index = {}
    for idx, name in enumerate(header_row):
        key = normalize_header(name)
        index.setdefault(key, []).append(idx)
    return index


def find_header_indices(header_index: dict[str, list[int]], candidates: list[str]) -> list[int]:
    indices: list[int] = []
    for candidate in candidates:
        normalized = normalize_header(candidate)
        indices.extend(header_index.get(normalized, []))
    return indices


def get_cell(row: list[str], indices: list[int]) -> str:
    for idx in indices:
        if idx < len(row):
            value = row[idx].strip()
            if value:
                return value
    return ""


def get_multi_cell(row: list[str], indices: list[int]) -> list[str]:
    """Return all non-empty values from the given column indices (preserves order)."""
    return [row[idx].strip() for idx in indices if idx < len(row) and row[idx].strip()]


_NONE_VALUES = frozenset({"none", "n/a", "no", "-", "–", "keine", "no co-author", "no co-authors"})


def clean_none_values(values: list[str]) -> list[str]:
    return [v for v in values if normalize_header(v) not in _NONE_VALUES]


# ── Case normalisation ──────────────────────────────────────────────────────
# Rules applied only when a string is >65 % uppercase letters:
#   1. Mixed-case tokens (e.g. AAArC, SfM) are assumed intentional → kept.
#   2. All-caps tokens that are common stop words → lowercased (except position 0).
#   3. All-caps tokens ≤ 3 letters (not stop words) → assumed acronym → kept.
#   4. Everything else → capitalized (first letter upper, rest lower).

_ACRONYM_MAX = 3

_STOP_WORDS = frozenset({
    # English
    "a", "an", "and", "as", "at", "but", "by", "for", "from",
    "in", "is", "nor", "of", "on", "or", "the", "to", "up", "via", "with",
    # German (after umlaut-stripping: für→fur, über→uber, etc.)
    "am", "an", "auf", "aus", "bei", "das", "dem", "den", "der", "des",
    "die", "ein", "fur", "im", "mit", "nach", "oder", "uber", "und",
    "von", "vor", "zu", "zur",
})


def _normalize_word(word: str, is_first: bool = False) -> str:
    m = re.match(r'^([^A-Za-z0-9]*)(.+?)([^A-Za-z0-9]*)$', word)
    if not m:
        return word
    pre, core, post = m.group(1), m.group(2), m.group(3)
    letters = re.sub(r'[^A-Za-z]', '', core)
    if not letters or not letters.isupper():          # mixed case → intentional
        return word
    if not is_first and letters.lower() in _STOP_WORDS:  # stop word → lowercase
        return pre + core.lower() + post
    if len(letters) <= _ACRONYM_MAX:                  # short all-caps → acronym
        return word
    return pre + core[0].upper() + core[1:].lower() + post


def normalize_case(text: str) -> str:
    """Convert predominantly ALL-CAPS text to capitalised words; leave normal text untouched."""
    if not text:
        return text
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return text
    if sum(1 for c in letters if c.isupper()) / len(letters) <= 0.65:
        return text
    words = text.split()
    return ' '.join(_normalize_word(w, i == 0) for i, w in enumerate(words))


_FORMAT_MAP = {
    "presentation":   "Presentations",
    "prasentation":   "Presentations",  # Präsentation
    "vortrag":        "Presentations",
    "paper":          "Presentations",
    "poster":         "Posters",
    "posterbeitrag":  "Posters",
    "poster contribution": "Posters",
    "poster session": "Posters",
    "roundtable":     "Roundtables",
    "round table":    "Roundtables",
    "roundtable discussion": "Roundtables",
}


def normalize_format(value: str) -> str:
    return _FORMAT_MAP.get(normalize_header(value), "")


def read_csv(path: Path, colmap: dict) -> list[dict]:
    """Read the exported CSV into canonical submission dicts.

    This code preserves duplicate column headers and chooses the first
    non-empty value among duplicate header groups.
    """
    defaults = {
        "authors": ["Author / Presenter", "Author:in/ Vortragende:r"],
        "co_authors": ["Co-authors", "Co-author", "Mitautor:innen"],
        "institution": ["Institutional affiliation", "Institutionelle Zugehörigkeit", "Institution"],
        "title": ["Title of the contribution", "Titel des Beitrags"],
        "abstract": [
            "Abstract (approx. 2–3 sentences)",
            "Abstract (approx. 2-3 sentences)",
            "Abstract (approx. 150 words)",
            "Abstract",
        ],
        "track": [],
        "keywords": ["Keywords (3-5)", "Schlagwörter"],
        "format": ["Format of the contribution", "Format des Beitrags"],
        "language": ["Language of the contribution:", "Sprache des Beitrags:"],
        "first_name": ["First name", "Vorname"],
        "last_name": ["Last name", "Nachname"],
    }

    column_candidates = {
        key: normalize_column_spec(colmap.get(key, defaults.get(key, []))) or defaults.get(key, [])
        for key in defaults
    }

    submissions = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        header_index = build_header_index(header)

        title_indices = find_header_indices(header_index, column_candidates["title"])
        authors_indices = find_header_indices(header_index, column_candidates["authors"])
        coauthor_indices = find_header_indices(header_index, column_candidates["co_authors"])
        # Google Forms exports overflow co-author inputs as empty-header columns adjacent to a Co-authors column.
        empty_indices = header_index.get("", [])
        for cidx in list(coauthor_indices):
            for eidx in empty_indices:
                if eidx == cidx + 1 and eidx not in coauthor_indices:
                    coauthor_indices.append(eidx)
        abstract_indices = find_header_indices(header_index, column_candidates["abstract"])
        track_indices = find_header_indices(header_index, column_candidates["track"])
        keywords_indices = find_header_indices(header_index, column_candidates["keywords"])
        institution_indices = find_header_indices(header_index, column_candidates["institution"])
        format_indices = find_header_indices(header_index, column_candidates["format"])
        language_indices = find_header_indices(header_index, column_candidates["language"])
        first_name_indices = find_header_indices(header_index, column_candidates["first_name"])
        last_name_indices = find_header_indices(header_index, column_candidates["last_name"])

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue

            format_value = get_cell(row, format_indices)

            title = normalize_case(get_cell(row, title_indices))
            if not title:
                continue

            abstract = get_cell(row, abstract_indices)
            if not abstract or normalize_header(abstract) in _NONE_VALUES:
                # Skip registrations without a real contribution (e.g. "I just want to attend")
                continue

            authors = normalize_case(get_cell(row, authors_indices))
            if not authors:
                first_name = get_cell(row, first_name_indices)
                last_name = get_cell(row, last_name_indices)
                if first_name or last_name:
                    authors = normalize_case(
                        " ".join(part for part in (first_name, last_name) if part)
                    )

            co_authors = [normalize_case(v) for v in clean_none_values(get_multi_cell(row, coauthor_indices))]
            institution = normalize_case(get_cell(row, institution_indices))
            keywords = get_cell(row, keywords_indices)
            if normalize_header(keywords) in _NONE_VALUES:
                keywords = ""
            track = get_cell(row, track_indices) or normalize_format(format_value) or "Other"

            submissions.append(
                {
                    "authors": authors,
                    "co_authors": co_authors,
                    "institution": institution,
                    "title": title,
                    "abstract": abstract,
                    "track": track,
                    "keywords": keywords,
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
    out_dir.mkdir(parents=True, exist_ok=True)

    logo_src = ROOT / "data" / "Logo FANT.png"
    has_logo = logo_src.exists()
    if has_logo:
        shutil.copy(logo_src, out_dir / "logo.png")

    intro_path = ROOT / "data" / "intro.html"
    intro_html = intro_path.read_text(encoding="utf-8") if intro_path.exists() else ""

    try:
        from weasyprint import HTML as WPHtml
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is unavailable. Install the required system and Python dependencies "
            "to generate the PDF."
        ) from exc

    i18n = cfg.get("i18n") or {}
    generated = date.today().isoformat()

    for lang_code, t in i18n.items():
        html_name = "index.html" if lang_code == "de" else f"index-{lang_code}.html"
        ctx = {
            "conf": cfg["conference"],
            "sessions": sessions,
            "total": total,
            "generated": generated,
            "has_logo": has_logo,
            "intro": intro_html,
            "t": t,
            "lang": t.get("lang_attr", lang_code),
        }

        (out_dir / html_name).write_text(
            env.get_template("boc_web.html.j2").render(**ctx), encoding="utf-8"
        )

        pdf_name = t.get("pdf_file", f"book_of_contents_{lang_code}.pdf")
        WPHtml(
            string=env.get_template("boc_pdf.html.j2").render(**ctx),
            base_url=str(TEMPLATES),
        ).write_pdf(str(out_dir / pdf_name))

    print(f"Rendered {total} entries → {out_dir}/  ({len(i18n)} language(s))")


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
