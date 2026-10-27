"""Link each candidate to Chicago Electoral Board objection cases for this election.

Input:
  data/candidates/candidates_cboe.csv
  every "Library of Electoral Board Decisions" .xlsx saved by scripts/fetch_cboe.py

Status on 2026-10-27: the newest library is the 2026 edition (posted 2026-04);
it has no cases for the Feb 2027 election yet (objections are filed Oct 27 – Nov 2,
2026). Until a library with case IDs starting CASE_ID_PREFIX appears, every
candidate is written with objection_data_status = "no_cases_published_yet".

How cases are found: the library mixes several column layouts (older rows:
Election / Objector / Candidate / Office / Case / Decision; 2024+ rows: Election /
Case / Objector / Candidate / Party / Office / District / Decision) plus
"consolidated with" rows holding only a case ID. The 2027 layout is unknown, so
this script does not rely on column positions: any row with a cell matching
CASE_ID_PATTERN is kept, with every cell value and hyperlink copied raw.
OPEN QUESTION: once 2027 rows exist, decide which cell is the candidate name and
which is the decision, and set CASE_COLUMNS_2027 accordingly.

Outputs:
  data/candidates/electoral_board_cases_2027.csv  raw case rows (all cells + links)
  data/candidates/ballot_status.csv               per candidate: matched case IDs + decisions

Usage:
  python scripts/build_ballot_status.py
"""

import csv
import re
from pathlib import Path

import openpyxl

from names import normalization_steps_on, normalize_name

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CBOE_CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
CBOE_DOCUMENTS_DIR = REPO_ROOT / "data" / "raw" / "cboe" / "documents"
CASES_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "electoral_board_cases_2027.csv"
STATUS_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "ballot_status.csv"

# Library files are found by this file-name pattern under CBOE_DOCUMENTS_DIR.
LIBRARY_FILE_GLOB = "*Electoral Board Decisions*.xlsx"

# Case IDs look like "26-EB-SS-001", "19-EB-ALD-069". The 2027 municipal
# election's cases are expected to start "27-EB-" (assumption from the pattern
# of earlier years — OPEN QUESTION until the first 2027 cases are posted).
CASE_ID_PREFIX = "27-EB-"
CASE_ID_PATTERN = re.compile(r"\b" + re.escape(CASE_ID_PREFIX) + r"[A-Z]+-\d+\b")

# Which raw cell (1-based) holds the candidate name and the decision for 2027
# rows. None until the layout is seen; while None, cases are written raw but
# not linked to candidates.
CASE_COLUMNS_2027 = {"candidate_cell": None, "decision_cell": None}

MAX_CELLS = 10  # library rows have had at most 8 used columns


def find_library_files():
    return sorted(CBOE_DOCUMENTS_DIR.rglob(LIBRARY_FILE_GLOB))


def read_cases(library_path):
    """Every row in one library containing a CASE_ID_PREFIX case ID, cells kept raw."""
    worksheet = openpyxl.load_workbook(library_path).active
    cases = []
    for row_number, row in enumerate(worksheet.iter_rows(), start=1):
        cell_texts = ["" if cell.value is None else str(cell.value).strip() for cell in row[:MAX_CELLS]]
        found_ids = [match for text in cell_texts for match in CASE_ID_PATTERN.findall(text)]
        if not found_ids:
            continue
        record = {
            "library_file": library_path.name,
            "row_number": row_number,
            "case_ids_in_row": "; ".join(found_ids),
        }
        for index, cell in enumerate(row[:MAX_CELLS], start=1):
            record[f"cell_{index}"] = cell_texts[index - 1]
            record[f"cell_{index}_link"] = cell.hyperlink.target if cell.hyperlink else ""
        cases.append(record)
    return cases


def main():
    library_files = find_library_files()
    print("library files checked:", [path.name for path in library_files] or "none")
    all_cases = []
    for library_path in library_files:
        all_cases.extend(read_cases(library_path))
    print(f"rows with a {CASE_ID_PREFIX} case ID: {len(all_cases)}")

    case_columns = ["library_file", "row_number", "case_ids_in_row"]
    for index in range(1, MAX_CELLS + 1):
        case_columns += [f"cell_{index}", f"cell_{index}_link"]
    with open(CASES_OUTPUT_PATH, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=case_columns)
        writer.writeheader()
        writer.writerows(all_cases)

    # Link candidates to cases only once the 2027 layout has been set by hand.
    candidate_cell = CASE_COLUMNS_2027["candidate_cell"]
    decision_cell = CASE_COLUMNS_2027["decision_cell"]
    if not all_cases:
        data_status = "no_cases_published_yet"
    elif candidate_cell is None:
        data_status = "cases_found_layout_not_set"  # see OPEN QUESTION in the docstring
    else:
        data_status = "linked"

    with open(CBOE_CANDIDATES_PATH, newline="") as input_file:
        candidates = list(csv.DictReader(input_file))
    status_rows = []
    for candidate in candidates:
        matched_case_ids, decisions = [], []
        if data_status == "linked":
            candidate_normalized = normalize_name(candidate["ballot_name_raw"])
            for case in all_cases:
                if normalize_name(case[f"cell_{candidate_cell}"]) == candidate_normalized:
                    matched_case_ids.append(case["case_ids_in_row"])
                    decisions.append(case[f"cell_{decision_cell}"] if decision_cell else "")
        status_rows.append({
            "candidate_id": candidate["candidate_id"],
            "office_code": candidate["office_code"],
            "district_number": candidate["district_number"],
            "ballot_name_raw": candidate["ballot_name_raw"],
            "objection_data_status": data_status,
            # Exact normalized-name match only; same name in two races would match both.
            # OPEN QUESTION: also require the office cell to match, once the layout is known.
            "matched_case_ids": " | ".join(matched_case_ids),
            "matched_decisions": " | ".join(decisions),
            "normalization_steps_on": normalization_steps_on(),
        })
    with open(STATUS_OUTPUT_PATH, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(status_rows[0].keys()))
        writer.writeheader()
        writer.writerows(status_rows)
    print(f"objection data status: {data_status}")
    print(f"wrote {CASES_OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {STATUS_OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(status_rows)} candidates)")


if __name__ == "__main__":
    main()
