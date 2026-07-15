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
from datetime import date, datetime
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


_COLUMN_DEFAULTS = {
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


def _parse_submission_rows(rows: list[list[str]], colmap: dict) -> list[dict]:
    """Parse an iterable of string rows (header first) into submission dicts."""
    column_candidates = {
        key: normalize_column_spec(colmap.get(key, _COLUMN_DEFAULTS.get(key, []))) or _COLUMN_DEFAULTS.get(key, [])
        for key in _COLUMN_DEFAULTS
    }

    header = rows[0] if rows else []
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
    first_name_indices = find_header_indices(header_index, column_candidates["first_name"])
    last_name_indices = find_header_indices(header_index, column_candidates["last_name"])

    submissions = []
    for row in rows[1:]:
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


def read_xlsx(path: Path, colmap: dict) -> list[dict]:
    """Read submissions directly from an xlsx file (first sheet)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = [
        [str(cell) if cell is not None else "" for cell in row]
        for row in ws.iter_rows(values_only=True)
    ]
    return _parse_submission_rows(rows, colmap)


def read_csv(path: Path, colmap: dict) -> list[dict]:
    """Read the exported CSV into canonical submission dicts."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return _parse_submission_rows(rows, colmap)


def group_by_session(submissions: list[dict], cfg: dict) -> list[dict]:
    """Return ordered list of {"track": str, "entries": [...]} blocks."""
    order = cfg.get("session_order") or []
    by_track: dict[str, list[dict]] = {}
    for s in submissions:
        by_track.setdefault(s["track"], []).append(s)

    # Sort entries within a track by title for stable, reproducible output.
    for entries in by_track.values():
        entries.sort(key=lambda e: e["authors"].split()[-1].lower())

    ordered = [t for t in order if t in by_track]
    rest = sorted(t for t in by_track if t not in order)
    return [{"track": t, "entries": by_track[t]} for t in ordered + rest]


def load_schedule() -> list[dict]:
    """Read FANT26_schedule.xlsx and return schedule rows with presenter info."""
    xlsx_path = ROOT / "data" / "FANT26_schedule.xlsx"
    if not xlsx_path.exists():
        return []
    try:
        import openpyxl
    except ImportError:
        return []

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    presenters_by_session: dict[str, list[dict]] = {}
    if "Presentors" in wb.sheetnames:
        ws_p = wb["Presentors"]
        rows = list(ws_p.iter_rows(values_only=True))
        for row in rows[1:]:
            if not row or not row[3]:
                continue
            last_name = str(row[0]).strip() if row[0] else ""
            first_name = str(row[1]).strip() if row[1] else ""
            topic = normalize_case(str(row[2]).strip()) if row[2] else ""
            session = str(row[3]).strip()
            name_parts = [p for p in (first_name, last_name) if p]
            name = normalize_case(" ".join(name_parts))
            presenters_by_session.setdefault(session, []).append({"name": name, "topic": topic})

    schedule = []
    if "Schedule" in wb.sheetnames:
        ws_s = wb["Schedule"]
        for row in ws_s.iter_rows(values_only=True):
            if not row or row[0] == "Module":
                continue
            module = str(row[0]).strip() if row[0] else ""
            time_val = row[1]
            if hasattr(time_val, "strftime"):
                time_str = time_val.strftime("%H:%M")
            elif isinstance(time_val, datetime):
                time_str = time_val.strftime("%H:%M")
            else:
                time_str = str(time_val) if time_val else ""
            presenters = presenters_by_session.get(module, [])
            schedule.append({
                "module": module,
                "time": time_str,
                "is_session": bool(presenters),
                "presenters": presenters,
            })
    return schedule


def load_intro(lang_code: str) -> str:
    """Load intro HTML, preferring mammoth-converted docx for DE, HTML files for others."""
    docx_path = ROOT / "data" / "intro.html.docx"
    if lang_code == "de" and docx_path.exists():
        try:
            import mammoth
            with open(docx_path, "rb") as fh:
                return mammoth.convert_to_html(fh).value
        except Exception:
            pass
    lang_intro = ROOT / "data" / f"intro-{lang_code}.html"
    fallback_intro = ROOT / "data" / "intro.html"
    intro_path = lang_intro if lang_intro.exists() else fallback_intro
    return intro_path.read_text(encoding="utf-8") if intro_path.exists() else ""


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

    try:
        from weasyprint import HTML as WPHtml
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is unavailable. Install the required system and Python dependencies "
            "to generate the PDF."
        ) from exc

    i18n = cfg.get("i18n") or {}
    generated = date.today().isoformat()
    schedule = load_schedule()

    for lang_code, t in i18n.items():
        intro_html = load_intro(lang_code)

        html_name = "index.html" if lang_code == "de" else f"index-{lang_code}.html"
        ctx = {
            "conf": cfg["conference"],
            "sessions": sessions,
            "total": total,
            "generated": generated,
            "has_logo": has_logo,
            "intro": intro_html,
            "schedule": schedule,
            "t": t,
            "lang": t.get("lang_attr", lang_code),
        }

        (out_dir / html_name).write_text(
            env.get_template("boc_web.html.j2").render(**ctx), encoding="utf-8"
        )

        pdf_name = t.get("pdf_file", f"book_of_contents_{lang_code}.pdf")
        WPHtml(
            string=env.get_template("boc_pdf.html.j2").render(**ctx),
            base_url=str(out_dir),
        ).write_pdf(str(out_dir / pdf_name))

    print(f"Rendered {total} entries → {out_dir}/  ({len(i18n)} language(s))")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", "--csv", dest="input", help="override the input file path from config.yml")
    p.add_argument("--out", default="site", help="output directory (default: site)")
    args = p.parse_args()

    cfg = load_config()
    colmap = cfg["input"]["columns"]

    # Prefer xlsx over csv: try xlsx path first, fall back to csv_path from config.
    input_override = args.input
    if input_override:
        input_path = ROOT / input_override
        suffix = input_path.suffix.lower()
    else:
        xlsx_path = ROOT / cfg["input"].get("xlsx_path", "data/FANT26_merged.xlsx")
        csv_path  = ROOT / cfg["input"]["csv_path"]
        if xlsx_path.exists():
            input_path, suffix = xlsx_path, ".xlsx"
        else:
            input_path, suffix = csv_path, ".csv"

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    if suffix == ".xlsx":
        submissions = read_xlsx(input_path, colmap)
    else:
        submissions = read_csv(input_path, colmap)

    if not submissions:
        print("No submissions found in input file.", file=sys.stderr)
        return 1

    sessions = group_by_session(submissions, cfg)
    render(cfg, sessions, ROOT / args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
