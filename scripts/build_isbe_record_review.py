"""Build the review sheet for the one match we confirm: CBOE ballot candidate ->
ISBE candidate record. One row per (candidate, ISBE record with a matching last
name), with an empty `accept` column for you to mark.

Why this is the only confirmation (PLAN.md §3a): CBOE and ISBE share no ID.
Illinois Sunshine starts from ISBE records, so it never needs this step; we start
from the ballot. Once a record is confirmed, its committees follow automatically
(scripts/build_candidate_committee.py), as on Sunshine.

Input:  data/crosswalk/candidate_committee_proposals.csv  (scripts/propose_committee_matches.py)
Output: data/crosswalk/candidate_isbe_review.csv          (you edit this file)

Columns you fill in (kept when this script is rerun — matched by REVIEW_KEY_COLUMNS):
  accept        "yes" / "no" (blank = not reviewed yet)
  reviewed_by   your initials + date, or "agent_<date>"; the rule writes RULE_REVIEWER_LABEL
  review_notes  the evidence used

Rows marked by a person or agent that no longer appear in the proposals are kept
at the bottom with rule_outcome = "no_longer_proposed", so no review work is dropped
silently. Rows marked only by the rule are not kept (the rule recomputes them).

Then run scripts/apply_isbe_record_rule.py (marks the clear cases) and
scripts/build_candidate_committee.py.

Usage:
  python scripts/build_isbe_record_review.py
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PROPOSALS_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_proposals.csv"
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_isbe_review.csv"

# Proposal rows that carry an ISBE candidate record (with or without committees).
RECORD_EVIDENCE_SOURCES = {"cmte_candidate_link", "isbe_candidate_no_committee_link"}

# Columns you edit, and the columns that identify a row across reruns.
REVIEW_INPUT_COLUMNS = ["accept", "reviewed_by", "review_notes"]
REVIEW_KEY_COLUMNS = ["candidate_id", "isbe_candidate_id"]

# reviewed_by values written by scripts/apply_isbe_record_rule.py (RULE_REVIEWER_LABEL and
# RETIRED_RULE_REVIEWER_LABELS there). Rule marks are not kept for rows no longer proposed.
RULE_REVIEWER_LABEL = "rule_v4"
RETIRED_RULE_REVIEWER_LABELS = {"rule_v2", "rule_v3"}

# Columns copied from the proposals (one value per candidate x ISBE record).
RECORD_COLUMNS = [
    "candidate_id", "office_code", "district_number", "ballot_name_raw", "also_filed_as",
    "isbe_candidate_id", "isbe_last_name", "isbe_first_name", "isbe_office",
    "isbe_district_raw", "isbe_district_number", "isbe_district_basis",
    "last_name_match_type", "district_matches", "first_word_matches", "suffix_matches",
    "isbe_election_records", "has_2027_election_record", "normalization_steps_on",
]

# Sheet column order. rule_outcome / rule_reason are filled by apply_isbe_record_rule.py.
SHEET_COLUMNS = [
    "rule_outcome", "rule_reason", *REVIEW_INPUT_COLUMNS,
    "candidate_id", "ballot_name_raw", "isbe_candidate_id", "isbe_last_name", "isbe_first_name",
    "district_number", "isbe_district_raw", "last_name_match_type",
    "district_matches", "first_word_matches", "suffix_matches",
    "linked_committee_count", "linked_committees", "other_candidates_matching_record",
    "isbe_election_records", "has_2027_election_record",
    "also_filed_as", "office_code", "isbe_office", "isbe_district_number", "isbe_district_basis", "normalization_steps_on",
]


def describe_committee(row):
    """'ID Name (status, type)' — enough to recognize a committee in the sheet."""
    return f"{row['committee_id']} {row['committee_name']} ({row['committee_status']}, {row['committee_type'] or 'no type'})"


def main():
    proposals = pd.read_csv(PROPOSALS_PATH, dtype=str, keep_default_na=False)
    record_rows = proposals[proposals["evidence_source"].isin(RECORD_EVIDENCE_SOURCES)]

    # One row per candidate x ISBE record, listing the committees ISBE links to the record.
    review = record_rows.drop_duplicates(REVIEW_KEY_COLUMNS)[RECORD_COLUMNS].copy()
    linked = record_rows[record_rows["evidence_source"] == "cmte_candidate_link"].copy()
    linked["committee_description"] = linked.apply(describe_committee, axis=1)
    committees_by_record = linked.groupby("isbe_candidate_id")["committee_description"].agg(
        lambda descriptions: " | ".join(sorted(set(descriptions))))
    review["linked_committees"] = review["isbe_candidate_id"].map(committees_by_record).fillna("")
    review["linked_committee_count"] = review["isbe_candidate_id"].map(
        linked.groupby("isbe_candidate_id")["committee_id"].nunique()).fillna(0).astype(int)

    # Other CBOE candidates whose name also matches this ISBE record (e.g. duplicate filings).
    candidates_by_record = review.groupby("isbe_candidate_id")["candidate_id"].agg(set)
    review["other_candidates_matching_record"] = review.apply(
        lambda row: "; ".join(sorted(candidates_by_record[row["isbe_candidate_id"]] - {row["candidate_id"]})),
        axis=1)

    # Carry over anything already marked in an existing sheet.
    for column in REVIEW_INPUT_COLUMNS + ["rule_outcome", "rule_reason"]:
        review[column] = ""
    carried_over = 0
    orphaned = pd.DataFrame()
    if REVIEW_PATH.exists():
        previous = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)
        marked = previous[(previous[REVIEW_INPUT_COLUMNS] != "").any(axis=1)]
        marked_by_key = marked.drop_duplicates(REVIEW_KEY_COLUMNS).set_index(REVIEW_KEY_COLUMNS)
        review_keys = review.set_index(REVIEW_KEY_COLUMNS).index
        for row_position, key in enumerate(review_keys):
            if key in marked_by_key.index:
                for column in REVIEW_INPUT_COLUMNS:
                    review.iat[row_position, review.columns.get_loc(column)] = marked_by_key.at[key, column]
                carried_over += 1
        orphaned = marked[~marked.set_index(REVIEW_KEY_COLUMNS).index.isin(review_keys)
                          & ~marked["reviewed_by"].isin({RULE_REVIEWER_LABEL} | RETIRED_RULE_REVIEWER_LABELS)].copy()
        orphaned["rule_outcome"] = "no_longer_proposed"

    review = review.sort_values(["candidate_id", "isbe_candidate_id"])
    review = pd.concat([review[SHEET_COLUMNS], orphaned], ignore_index=True)
    review = review.reindex(columns=SHEET_COLUMNS).fillna("")
    review.to_csv(REVIEW_PATH, index=False)

    no_record = proposals.loc[~proposals["candidate_id"].isin(review["candidate_id"]), "candidate_id"].nunique()
    print(f"{len(review) - len(orphaned)} candidate x ISBE record rows for "
          f"{review['candidate_id'].nunique()} candidates; {no_record} candidates have no ISBE record")
    print(f"marks carried over: {carried_over}; marked rows no longer proposed: {len(orphaned)}")
    print(f"wrote {REVIEW_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
