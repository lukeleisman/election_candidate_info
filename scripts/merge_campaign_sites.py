"""Combine the per-batch campaign-site files into one table and check it against the CBOE list.

Inputs:
  data/endorsements/campaign_sites_parts/*.csv   one file per batch (A-D), written by agents
  data/candidates/candidates_cboe.csv            official candidate list (read-only)

Output:
  data/endorsements/candidate_campaign_sites.csv  all part rows, sorted by candidate_id

Checks (printed, never silently fixed):
  - candidates in scope with no row in any part file (missing)
  - candidate_ids appearing more than once across parts (duplicates; all copies are kept)
  - candidate_ids in the parts that are not in scope on the CBOE list (unexpected)
  - "found" rows missing evidence_url or evidence_quote
  - status values outside ALLOWED_STATUSES
Exits with code 1 if any check fails, so `make` stops.

Process and rules: sessions/2026-11-04-endorsements.md, "Candidate campaign sites".

Usage:
  python scripts/merge_campaign_sites.py
"""

import csv
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = REPO_ROOT / "data/candidates/candidates_cboe.csv"
PARTS_DIRECTORY = REPO_ROOT / "data/endorsements/campaign_sites_parts"
OUTPUT_FILE = REPO_ROOT / "data/endorsements/candidate_campaign_sites.csv"

# User decision 2026-11-05: Police District Council (PDC) left out for now.
SCOPE_OFFICES = {"MAYOR", "CLERK", "TREAS", "ALD"}

# Status definitions live in the session log; these are the only allowed values.
ALLOWED_STATUSES = {"found", "needs_confirmation", "ambiguous", "none_found"}

OUTPUT_COLUMNS = [
    "candidate_id", "ballot_name_raw", "office_code", "ward", "status",
    # User decision 2026-11-05: several site columns, each with a plain note (old site, dead
    # domain, official ward site, ...). Replaces the old single site_url column (A converted).
    "campaign_site_url", "campaign_site_note",
    "ward_office_url", "ward_office_note",
    "other_site_urls", "other_site_note",
    "endorsements_url", "evidence_url", "evidence_quote", "endorsements_seen_url",
    "endorsements_seen_raw", "found_via", "checked_on", "entered_by", "review_status", "notes",
]


def read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    # Candidates the parts should cover.
    candidates_in_scope = {
        row["candidate_id"]
        for row in read_csv_rows(CANDIDATES_FILE)
        if row["office_code"] in SCOPE_OFFICES
    }

    # Read every part file; remember which file each row came from (for the report only).
    part_rows = []
    for part_path in sorted(PARTS_DIRECTORY.glob("*.csv")):
        rows_in_part = read_csv_rows(part_path)
        print(f"{part_path.name}: {len(rows_in_part)} rows")
        for row in rows_in_part:
            extra_columns = set(row) - set(OUTPUT_COLUMNS)
            if extra_columns:
                print(f"  WARNING {part_path.name} {row.get('candidate_id')}: "
                      f"unexpected columns dropped: {sorted(extra_columns)}")
            part_rows.append(row)

    id_counts = Counter(row["candidate_id"] for row in part_rows)
    missing_ids = sorted(candidates_in_scope - set(id_counts))
    duplicate_ids = sorted(candidate_id for candidate_id, count in id_counts.items() if count > 1)
    unexpected_ids = sorted(set(id_counts) - candidates_in_scope)
    found_without_evidence = sorted(
        row["candidate_id"] for row in part_rows
        if row["status"] == "found"
        and not (row.get("evidence_url", "").strip() and row.get("evidence_quote", "").strip())
    )
    bad_statuses = sorted(
        (row["candidate_id"], row["status"]) for row in part_rows
        if row["status"] not in ALLOWED_STATUSES
    )

    # Write everything (duplicates included, so nothing is hidden), sorted by candidate_id.
    part_rows.sort(key=lambda row: row["candidate_id"])
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(part_rows)

    # Report.
    print(f"\nWrote {len(part_rows)} rows to {OUTPUT_FILE.relative_to(REPO_ROOT)}")
    print(f"In scope on CBOE list: {len(candidates_in_scope)}")
    print("Status counts:", dict(Counter(row["status"] for row in part_rows)))
    problems = {
        "missing (in scope, no row)": missing_ids,
        "duplicate candidate_id": duplicate_ids,
        "not in scope on CBOE list": unexpected_ids,
        "found but no evidence_url/evidence_quote": found_without_evidence,
        "status not allowed": bad_statuses,
    }
    for label, items in problems.items():
        print(f"{label}: {len(items)}")
        for item in items:
            print(f"  {item}")
    if any(problems.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
