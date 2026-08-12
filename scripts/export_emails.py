#!/usr/bin/env python3
"""Export the submitter email list from the submissions spreadsheet for local use.

Run this locally after updating the input xlsx (input.xlsx_path in config.yml):

    python scripts/export_emails.py

Writes data/emails.txt as a single semicolon-separated line (deduplicated,
sorted) — paste that straight into Horde's compose/BCC field.

data/emails.txt is git-ignored on purpose: this repo is public, and unlike
the submission CSV/xlsx (which the README already warns about), an email
list has no reason to ever leave your machine. This script never touches
site/ either, so it can't leak into the deployed GitHub Pages output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

EMAIL_HEADER_CANDIDATES = ["Email address", "E-Mail-Adresse", "E-Mail", "Email"]


def main() -> int:
    cfg = build.load_config()
    xlsx_path = build.ROOT / cfg["input"].get("xlsx_path", "data/submissions.xlsx")
    if not xlsx_path.exists():
        print(f"Input file not found: {xlsx_path}", file=sys.stderr)
        return 1

    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = [
        [str(cell) if cell is not None else "" for cell in row]
        for row in ws.iter_rows(values_only=True)
    ]
    if not rows:
        print("No rows found in input file.", file=sys.stderr)
        return 1

    header_index = build.build_header_index(rows[0])
    email_indices = build.find_header_indices(header_index, EMAIL_HEADER_CANDIDATES)
    if not email_indices:
        print(f"No email column found (looked for {EMAIL_HEADER_CANDIDATES}).", file=sys.stderr)
        return 1

    emails = set()
    for row in rows[1:]:
        value = build.get_cell(row, email_indices)
        # A cell can itself hold more than one address (comma- or
        # semicolon-separated), e.g. when co-submitters share a field.
        for part in value.replace(";", ",").split(","):
            part = part.strip()
            if part:
                emails.add(part)

    out_path = build.ROOT / "data" / "emails.txt"
    out_path.write_text("; ".join(sorted(emails, key=str.lower)) + "\n", encoding="utf-8")
    print(f"Wrote {len(emails)} unique email address(es) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
