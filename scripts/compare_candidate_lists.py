"""Compare the official CBOE candidate list with the unofficial lists in data/input/.

Official list: data/candidates/candidates_cboe.csv (scripts/parse_cboe_filing_report.py).
Unofficial lists (COMPARISON_LISTS below) are cross-checks only; nothing is
copied from them into the official table.

Matching rule — the only rule that produces a "matched" row:
  same race (office code + ward/district) AND identical name after the
  normalization steps switched on in NAME_NORMALIZATION_STEPS (scripts/names.py).
Everything else is evidence for you to judge, never an automatic match:
  - near_miss_cboe_names: CBOE names in the same race within
    NEAR_MISS_MAX_EDIT_DISTANCE edits of the list name (after normalization)
  - same_last_word_cboe_names: CBOE names in the same race whose last word
    (after normalization) equals the list name's last word

Output: data/candidates/candidate_list_comparison.csv, one row per
  (list, list entry) plus one row per (list, CBOE candidate not found in that list).
  Columns include both raw and normalized names so each decision can be checked.

Usage:
  python scripts/compare_candidate_lists.py
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

from names import edit_distance, normalization_steps_on, normalize_name

# ---------------------------------------------------------------------------
# Configuration — every judgment call lives here.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CBOE_CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "candidate_list_comparison.csv"

# Each unofficial list: file, which columns hold office / district / name, and
# a fixed office if the file has no office column. Offices not in
# LIST_OFFICE_TO_CBOE_CODE are reported and skipped.
COMPARISON_LISTS = {
    "notion_2026-10-26": {
        "path": REPO_ROOT / "data" / "input" / "candidates_2026-10-26_notion.csv",
        "office_column": "Office", "district_column": "Ward", "name_column": "Name",
        "fixed_office": None, "extra_columns": [],
    },
    "bluesky_2026-10-26": {
        "path": REPO_ROOT / "data" / "input" / "candidates_2026-10-26_bluesky.csv",
        "office_column": "Office", "district_column": "Ward", "name_column": "Name",
        "fixed_office": None, "extra_columns": [],
    },
    "pasted_2026-10-04": {
        "path": REPO_ROOT / "data" / "input" / "aldermanic_candidates_2027.csv",
        "office_column": None, "district_column": "Ward", "name_column": "Name",
        "fixed_office": "Alderman", "extra_columns": ["General status"],
    },
}

LIST_OFFICE_TO_CBOE_CODE = {
    "Alderman": "ALD",
    "Mayor": "MAYOR",
}

# Edit distance (on normalized names) at or below which a non-matching CBOE
# name in the same race is listed as a near miss for you to look at.
NEAR_MISS_MAX_EDIT_DISTANCE = 4

OUTPUT_COLUMNS = [
    "list_name", "status", "office_code", "district_number",
    "list_row_number", "list_name_raw", "list_extra",
    "cboe_candidate_id", "cboe_ballot_name_raw",
    "list_name_normalized", "cboe_name_normalized",
    "near_miss_cboe_names", "same_last_word_cboe_names",
    "normalization_steps_on",
]


def read_cboe():
    """CBOE candidates grouped by race: {(office_code, district_number): [row, ...]}."""
    by_race = defaultdict(list)
    with open(CBOE_CANDIDATES_PATH, newline="") as input_file:
        for row in csv.DictReader(input_file):
            row["name_normalized"] = normalize_name(row["ballot_name_raw"])
            by_race[(row["office_code"], row["district_number"])].append(row)
    return by_race


def read_list(config):
    """Rows of one unofficial list as dicts with office_code / district_number / name."""
    rows = []
    with open(config["path"], newline="") as input_file:
        for row_number, row in enumerate(csv.DictReader(input_file), start=2):
            office = config["fixed_office"] or row[config["office_column"]]
            rows.append({
                "row_number": row_number,
                "office_raw": office,
                "office_code": LIST_OFFICE_TO_CBOE_CODE.get(office),
                # CBOE leaves the district blank for citywide offices; so do the lists.
                "district_number": (row[config["district_column"]] or "").strip(),
                "name_raw": row[config["name_column"]],
                "extra": "; ".join(f"{column}={row[column]}" for column in config["extra_columns"]),
            })
    return rows


def compare_one_list(list_name, list_rows, cboe_by_race):
    output_rows = []
    matched_cboe_ids = set()
    steps_on = normalization_steps_on()

    skipped_offices = Counter(row["office_raw"] for row in list_rows if row["office_code"] is None)
    for office, count in skipped_offices.items():
        print(f"  {list_name}: skipped {count} rows with unmapped office {office!r}")

    races_in_list = set()
    for list_row in list_rows:
        if list_row["office_code"] is None:
            continue
        race = (list_row["office_code"], list_row["district_number"])
        races_in_list.add(list_row["office_code"])
        list_normalized = normalize_name(list_row["name_raw"])
        race_candidates = cboe_by_race.get(race, [])
        exact = [c for c in race_candidates if c["name_normalized"] == list_normalized]

        near_misses = []
        same_last_word = []
        for candidate in race_candidates:
            if candidate in exact:
                continue
            distance = edit_distance(list_normalized, candidate["name_normalized"])
            if distance <= NEAR_MISS_MAX_EDIT_DISTANCE:
                near_misses.append(f"{candidate['ballot_name_raw']} (distance {distance})")
            if list_normalized.split()[-1:] == candidate["name_normalized"].split()[-1:]:
                same_last_word.append(candidate["ballot_name_raw"])

        if len(exact) == 1:
            status = "matched"
            matched_cboe_ids.add(exact[0]["candidate_id"])
        elif len(exact) > 1:
            status = "ambiguous_multiple_exact"  # never resolved automatically
        else:
            status = "list_only"
        output_rows.append({
            "list_name": list_name,
            "status": status,
            "office_code": list_row["office_code"],
            "district_number": list_row["district_number"],
            "list_row_number": list_row["row_number"],
            "list_name_raw": list_row["name_raw"],
            "list_extra": list_row["extra"],
            "cboe_candidate_id": "; ".join(c["candidate_id"] for c in exact),
            "cboe_ballot_name_raw": "; ".join(c["ballot_name_raw"] for c in exact),
            "list_name_normalized": list_normalized,
            "cboe_name_normalized": "; ".join(c["name_normalized"] for c in exact),
            "near_miss_cboe_names": "; ".join(near_misses),
            "same_last_word_cboe_names": "; ".join(same_last_word),
            "normalization_steps_on": steps_on,
        })

    # CBOE candidates missing from this list — only for offices the list covers at all.
    for (office_code, district_number), race_candidates in sorted(cboe_by_race.items()):
        if office_code not in races_in_list:
            continue
        for candidate in race_candidates:
            if candidate["candidate_id"] in matched_cboe_ids:
                continue
            output_rows.append({
                "list_name": list_name,
                "status": "cboe_only",
                "office_code": office_code,
                "district_number": district_number,
                "cboe_candidate_id": candidate["candidate_id"],
                "cboe_ballot_name_raw": candidate["ballot_name_raw"],
                "cboe_name_normalized": candidate["name_normalized"],
                "normalization_steps_on": steps_on,
            })
    return output_rows


def main():
    cboe_by_race = read_cboe()
    all_rows = []
    for list_name, config in COMPARISON_LISTS.items():
        list_rows = read_list(config)
        comparison = compare_one_list(list_name, list_rows, cboe_by_race)
        counts = Counter(row["status"] for row in comparison)
        print(f"{list_name}: {len(list_rows)} list rows -> {dict(counts)}")
        all_rows.extend(comparison)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
