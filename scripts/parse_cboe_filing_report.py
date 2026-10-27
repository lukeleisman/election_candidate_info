"""Parse the CBOE "Candidate Filing Report" PDF into a candidate table.

Input: a filing-report PDF saved by scripts/fetch_cboe.py, e.g.
  data/raw/cboe/documents/2026-10/Candidate Filing Report_20261026174516936.pdf

How the PDF is laid out (checked on the 2026-10-26 17:45 report, 20 pages):
  - Each page starts with a 2-line page header ("Page N of 20 ... Print Date",
    "CITY OF CHICAGO ... Print Time"). Page 1 also has a column-header line
    ("Filing Date  Office/District  Filing #  Candidate  Mailing Address  City  Zip").
  - Each candidate is a block of 2+ text lines. The first line starts with the
    filing date (MM/DD/YY); the next line starts with the filing time (HH:MM:SS).
    Long names and addresses wrap onto the following line(s).
  - The office ("Alderperson, 1st Ward" / "Mayor") is printed only on the first
    candidate of each office, with the district ("1st Ward" / "City Of Chicago")
    on the line below. Later candidates for the same office leave it blank.
  - The last page ends with "*** CANDIDATE TOTAL: 256 ***".

Words are assigned to columns by their left x-coordinate (COLUMN_LEFT_EDGES).
The script prints the boundaries and the header-line positions it sees so the
assignment can be checked against a new report.

Outputs:
  data/candidates/candidates_cboe.csv              committed; no addresses
  data/raw/cboe/candidates_with_addresses.csv      gitignored; adds mailing address/city/zip
  data/candidates/cboe_same_race_same_last_word.csv  review list: same race, same last name word

Validation (the script stops with an error if any fails):
  - number of candidates == the CANDIDATE TOTAL line
  - every ward 1..EXPECTED_WARD_COUNT has at least one candidate
  - no candidate has a blank name, date, or time

Usage:
  python scripts/parse_cboe_filing_report.py "<path to report pdf>"
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Configuration — every judgment call in the parse lives here.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
ADDRESS_OUTPUT_PATH = REPO_ROOT / "data" / "raw" / "cboe" / "candidates_with_addresses.csv"
# Candidates in the same race whose names end in the same word (e.g. two
# "MONIQUE SCOTT" filings in Ward 24). Written for review only; nothing is merged
# or dropped. Holds a same/different mailing-address flag, not the addresses.
SAME_SURNAME_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "cboe_same_race_same_last_word.csv"

# Left edge (PDF points) where each column begins. A word belongs to the last
# column whose left edge is <= the word's x0. Read off the 2026-10-26 report:
# header words start at Filing Date 31.6, Office/District 105.1, Filing # 295.3,
# Candidate 347.8, Mailing Address 492.6, City 611.1, Zip 672.6. Filing numbers
# are right-aligned under "Filing #" (x0 314.6–317.2), so that column starts a
# little left of its header to be safe.
COLUMN_LEFT_EDGES = [
    ("date_time", 0),
    ("office", 100),
    ("filing_number", 290),
    ("name", 345),
    ("address", 490),
    ("city", 605),
    ("zip", 665),
]

# Lines whose top is above this y (points from top of page) are the page header.
# The header's two lines sit at y=34.8 and y=56.0; the first data line on
# pages 2+ is at y=86.3.
PAGE_HEADER_BOTTOM_Y = 70

# Words whose tops differ by less than this are treated as the same text line.
SAME_LINE_TOLERANCE = 2.0

# Regular expressions for the start of a candidate block and its second line.
FILING_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{2}$")
FILING_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}:\d{2}$")
TOTAL_LINE_PATTERN = re.compile(r"CANDIDATE TOTAL:\s*(\d+)")

# How to join a name that wraps onto a second line.
# "DANIELLE CARTER-" + "WALTERS": joining with no space when the first part ends
# in "-" gives "CARTER-WALTERS". OPEN QUESTION: the PDF cannot tell us whether
# the hyphen is part of the name or a line-break hyphen; every hyphen-wrapped
# name is printed at the end of the run so you can check it against the PDF.
JOIN_HYPHEN_WRAPPED_NAMES_WITHOUT_SPACE = True

# Office text (from the PDF) -> short code used in candidate_id.
OFFICE_CODES = {
    "Mayor": "MAYOR",
    "Clerk": "CLERK",
    "Treasurer": "TREAS",
    "Alderperson": "ALD",
    # "Council Member, Chicago Police Department" = the CCPSA Police District
    # Councils (https://ccpsa.chicago.gov/2027dcelection/), one race per police district.
    "Council Member": "PDC",
}

EXPECTED_WARD_COUNT = 50

# Which candidate_id goes in the `candidate_id` column. Both are always written.
# <district> is the ward (ALD), police district (PDC), or 00 for citywide offices.
#   "by_order": <office>-<district>-<position of the candidate within that office in
#               this report>, e.g. ALD-01-003. OPEN QUESTION: a later CBOE report
#               could list candidates in a different order, changing the IDs.
#   "by_name":  <office>-<district>-<ballot name, uppercase, non-letters → "_">,
#               e.g. ALD-01-DANIEL_LA_SPATA. Changes if CBOE corrects a spelling.
# You choose; nothing downstream should be built before this is settled.
CANDIDATE_ID_SCHEME = "by_order"

PUBLIC_COLUMNS = [
    "candidate_id", "candidate_id_by_order", "candidate_id_by_name",
    "office", "office_code", "district_raw", "district_number",
    "filing_date", "filing_time", "filing_number", "ballot_name_raw",
    "source_pdf", "source_page",
]
ADDRESS_COLUMNS = PUBLIC_COLUMNS + ["mailing_address_raw", "city_raw", "zip_raw"]


def column_for(x0):
    """Name of the column a word starting at x0 falls in."""
    chosen = COLUMN_LEFT_EDGES[0][0]
    for column_name, left_edge in COLUMN_LEFT_EDGES:
        if x0 >= left_edge:
            chosen = column_name
    return chosen


def read_lines(pdf_path):
    """Return every non-header text line in reading order.

    Each line is a dict: {"page": page number (1-based), "top": y,
    "cells": {column name: text}, "text": whole line text}.
    """
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            words = page.extract_words()
            words.sort(key=lambda word: (word["top"], word["x0"]))
            current_line_words = []
            current_top = None
            grouped = []
            for word in words:
                if current_top is not None and abs(word["top"] - current_top) > SAME_LINE_TOLERANCE:
                    grouped.append(current_line_words)
                    current_line_words = []
                if not current_line_words:
                    current_top = word["top"]
                current_line_words.append(word)
            if current_line_words:
                grouped.append(current_line_words)

            for line_words in grouped:
                top = line_words[0]["top"]
                if top < PAGE_HEADER_BOTTOM_Y:
                    continue
                cells = {}
                for word in line_words:
                    column_name = column_for(word["x0"])
                    cells[column_name] = (cells.get(column_name, "") + " " + word["text"]).strip()
                lines.append({
                    "page": page_index + 1,
                    "top": top,
                    "cells": cells,
                    "text": " ".join(word["text"] for word in line_words),
                })
    return lines


def join_name_parts(parts):
    """Join wrapped name lines per JOIN_HYPHEN_WRAPPED_NAMES_WITHOUT_SPACE."""
    joined = ""
    for part in parts:
        if joined.endswith("-") and JOIN_HYPHEN_WRAPPED_NAMES_WITHOUT_SPACE:
            joined += part
        elif joined:
            joined += " " + part
        else:
            joined = part
    return joined


def number_from_district(district_text):
    """'1st Ward' -> 1; '22nd District' -> 22; 'City Of Chicago' -> None."""
    match = re.match(r"(\d+)(st|nd|rd|th) (Ward|District)$", district_text or "")
    return int(match.group(1)) if match else None


def name_slug(name):
    return re.sub(r"[^A-Z]+", "_", name.upper()).strip("_")


def parse(pdf_path):
    lines = read_lines(pdf_path)

    # Report the column-header line (page 1) so boundaries can be eyeballed.
    for line in lines:
        if "Office/District" in line["text"]:
            print("column header line, cells by column:", line["cells"])
            break
    print("column left edges:", COLUMN_LEFT_EDGES)

    reported_total = None
    blocks = []  # each block = list of lines belonging to one candidate
    for line in lines:
        total_match = TOTAL_LINE_PATTERN.search(line["text"])
        if total_match:
            reported_total = int(total_match.group(1))
            continue
        if "Office/District" in line["text"]:
            continue
        first_cell = line["cells"].get("date_time", "")
        if FILING_DATE_PATTERN.match(first_cell):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            raise ValueError(f"text before the first candidate: {line['text']!r}")

    candidates = []
    current_office = None
    current_district = None
    wrapped_names = []
    for block in blocks:
        first_line, continuation_lines = block[0], block[1:]

        # A new office is printed on the first line; its district on the second.
        office_text = first_line["cells"].get("office")
        if office_text:
            current_office = office_text
            current_district = continuation_lines[0]["cells"].get("office") if continuation_lines else None

        filing_time = None
        name_parts = [first_line["cells"].get("name", "")]
        address_parts = [first_line["cells"].get("address", "")]
        for line in continuation_lines:
            time_cell = line["cells"].get("date_time", "")
            if FILING_TIME_PATTERN.match(time_cell):
                filing_time = time_cell
            elif time_cell:
                raise ValueError(f"unexpected text in date column: {line['text']!r}")
            if line["cells"].get("name"):
                name_parts.append(line["cells"]["name"])
            if line["cells"].get("address"):
                address_parts.append(line["cells"]["address"])
            # City / zip have never wrapped; flag it if they ever do.
            if line["cells"].get("city") or line["cells"].get("zip"):
                raise ValueError(f"city/zip on a continuation line: {line['text']!r}")

        ballot_name = join_name_parts([part for part in name_parts if part])
        if len([part for part in name_parts if part]) > 1:
            wrapped_names.append((name_parts, ballot_name))

        office_base = current_office.split(",")[0]
        candidates.append({
            "office": current_office,
            "office_code": OFFICE_CODES[office_base],
            "district_raw": current_district,
            "district_number": number_from_district(current_district),
            "filing_date": first_line["cells"]["date_time"],
            "filing_time": filing_time,
            "filing_number": first_line["cells"].get("filing_number", ""),
            "ballot_name_raw": ballot_name,
            "source_pdf": Path(pdf_path).name,
            "source_page": first_line["page"],
            "mailing_address_raw": " ".join(part for part in address_parts if part),
            "city_raw": first_line["cells"].get("city", ""),
            "zip_raw": first_line["cells"].get("zip", ""),
        })

    # Assign both candidate_id variants.
    position_within_office = Counter()
    for candidate in candidates:
        office_key = (candidate["office_code"], candidate["district_number"])
        position_within_office[office_key] += 1
        district_text = f"{candidate['district_number'] or 0:02d}"
        prefix = f"{candidate['office_code']}-{district_text}"
        candidate["candidate_id_by_order"] = f"{prefix}-{position_within_office[office_key]:03d}"
        candidate["candidate_id_by_name"] = f"{prefix}-{name_slug(candidate['ballot_name_raw'])}"
        candidate["candidate_id"] = candidate[f"candidate_id_{CANDIDATE_ID_SCHEME}"]

    return candidates, reported_total, wrapped_names


def validate(candidates, reported_total):
    problems = []
    if reported_total is None:
        problems.append("no CANDIDATE TOTAL line found")
    elif len(candidates) != reported_total:
        problems.append(f"parsed {len(candidates)} candidates but report says {reported_total}")
    wards_present = {candidate["district_number"] for candidate in candidates if candidate["office_code"] == "ALD"}
    missing_wards = sorted(set(range(1, EXPECTED_WARD_COUNT + 1)) - wards_present)
    if missing_wards:
        problems.append(f"wards with no candidates: {missing_wards}")
    for candidate in candidates:
        for field in ("ballot_name_raw", "filing_date", "filing_time", "office"):
            if not candidate[field]:
                problems.append(f"blank {field}: {candidate}")
    for candidate in candidates:
        if candidate["office_code"] in ("ALD", "PDC") and candidate["district_number"] is None:
            problems.append(f"no ward/district number: {candidate}")
    duplicate_ids = [cid for cid, count in Counter(c["candidate_id"] for c in candidates).items() if count > 1]
    if duplicate_ids:
        problems.append(f"duplicate candidate_id: {duplicate_ids}")
    if problems:
        raise SystemExit("VALIDATION FAILED:\n  " + "\n  ".join(problems))


def last_name_word(ballot_name):
    """Last word of a ballot name, skipping suffixes (JR, SR, II, III, IV) and punctuation."""
    words = [word.strip(".,") for word in ballot_name.replace(",", " ").split()]
    words = [word for word in words if word and word not in ("JR", "SR", "II", "III", "IV")]
    return words[-1] if words else ""


def same_race_same_last_word(candidates):
    """Rows for every group of 2+ candidates in one race sharing a last name word."""
    groups = {}
    for candidate in candidates:
        key = (candidate["office_code"], candidate["district_number"], last_name_word(candidate["ballot_name_raw"]))
        groups.setdefault(key, []).append(candidate)
    review_rows = []
    for (office_code, district_number, last_word), group in groups.items():
        if len(group) < 2:
            continue
        group_addresses = {c["mailing_address_raw"] for c in group}
        if group_addresses == {""}:
            same_address = "no_address_in_pdf"  # citywide and police district rows print no address
        else:
            same_address = len(group_addresses) == 1
        for candidate in group:
            review_rows.append({
                "office_code": office_code,
                "district_number": district_number,
                "last_name_word": last_word,
                "candidate_id": candidate["candidate_id"],
                "ballot_name_raw": candidate["ballot_name_raw"],
                "filing_date": candidate["filing_date"],
                "filing_time": candidate["filing_time"],
                "filing_number": candidate["filing_number"],
                "group_size": len(group),
                "group_mailing_addresses_identical": same_address,
            })
    return review_rows


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    pdf_path = sys.argv[1]
    candidates, reported_total, wrapped_names = parse(pdf_path)
    validate(candidates, reported_total)

    write_csv(PUBLIC_OUTPUT_PATH, candidates, PUBLIC_COLUMNS)
    write_csv(ADDRESS_OUTPUT_PATH, candidates, ADDRESS_COLUMNS)
    review_rows = same_race_same_last_word(candidates)
    write_csv(SAME_SURNAME_OUTPUT_PATH, review_rows, list(review_rows[0].keys()) if review_rows else ["candidate_id"])

    print(f"\n{len(candidates)} candidates (report total: {reported_total})")
    for office_code, count in Counter(c["office_code"] for c in candidates).items():
        districts = sorted({c["district_number"] for c in candidates if c["office_code"] == office_code} - {None})
        print(f"  {office_code}: {count} candidates" + (f" in {len(districts)} districts {districts}" if districts else ""))
    print(f"candidate_id scheme in use: {CANDIDATE_ID_SCHEME}")
    print("\nnames that wrapped onto 2+ lines, and how they were joined (check against the PDF):")
    for parts, joined in wrapped_names:
        print(f"  {parts} -> {joined!r}")
    print(f"wrote {PUBLIC_OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {ADDRESS_OUTPUT_PATH.relative_to(REPO_ROOT)} (gitignored)")
    print(f"wrote {SAME_SURNAME_OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(review_rows)} rows to review)")


if __name__ == "__main__":
    main()
