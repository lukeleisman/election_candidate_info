"""Build a review sheet from the committee proposals: one row per proposal, with an
empty `accept` column for you to mark.

Input:  data/crosswalk/candidate_committee_proposals.csv  (scripts/propose_committee_matches.py)
Output: data/crosswalk/candidate_committee_review.csv     (you edit this file)

Rows are sorted into review groups by STRONG_ROW_RULE. The rule only sorts
rows; it never marks anything accepted.
  1_single_strong    candidate has exactly one row meeting the rule
  2_multiple_strong  candidate has 2+ rows meeting the rule — pick which belong
  3_no_strong        candidate has no row meeting the rule (weak, closed-only, or none)

Columns you fill in (kept when this script is rerun — matched by REVIEW_KEY_COLUMNS):
  accept          "yes" / "no" (blank = not reviewed yet)
  committee_role  candidate committee / ward organization / other
  reviewed_by     your initials, or "agent_<date>" if an agent did it
  review_notes    anything

When a rerun of the proposals adds new rows, they appear unmarked. Marked rows
that no longer appear in the proposals are kept at the bottom with
review_group = "0_no_longer_proposed", so no review work is ever dropped silently.

Then run scripts/apply_committee_review.py to write accepted rows to
data/crosswalk/candidate_committee.csv.

Usage:
  python scripts/build_committee_review.py
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PROPOSALS_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_proposals.csv"
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_review.csv"

# A proposal row is "strong" when ALL of these hold. Used only for sorting.
#   evidence_source == cmte_candidate_link   official ISBE candidate↔committee link
#   first_word_matches == True               ISBE first name matches the ballot name
#   committee_status == A                    committee is Active (F = Final / closed)
#   suffix_matches == True                   same Jr / Sr / II / III in both names (added
#                                            2026-10-27: Walter Burnett, Jr's committees were
#                                            matching his son, Walter "Red" Burnett)
# District match is deliberately NOT required: wards were redrawn for 2023, so
# older ISBE records carry old ward numbers.
STRONG_ROW_RULE = {
    "evidence_source": "cmte_candidate_link",
    "first_word_matches": "True",
    "committee_status": "A",
    "suffix_matches": "True",
}

# Closed (F) committees whose status date is on or after this date are flagged:
# money they raised before closing may fall inside the cycle. Mirrors the
# CYCLE_START_DATE OPEN QUESTION in PLAN_preliminary.md (options 2023-04-05 /
# 2023-03-01 / committee creation date); 2023-04-05 = day after the 2023 runoff.
CLOSED_AFTER_DATE_TO_FLAG = "2023-04-05"

# Columns you edit, and the columns that identify a proposal row across reruns.
REVIEW_INPUT_COLUMNS = ["accept", "committee_role", "reviewed_by", "review_notes"]
REVIEW_KEY_COLUMNS = ["candidate_id", "evidence_source", "isbe_candidate_id", "committee_id"]

# Proposal columns shown first in the sheet (all other proposal columns follow).
LEADING_COLUMNS = [
    "review_group", "strong_rule_met", "closed_after_flag_date",
    *REVIEW_INPUT_COLUMNS,
    "candidate_id", "ballot_name_raw", "committee_id", "committee_name",
    "committee_status", "committee_status_date", "committee_creation_date",
    "evidence_source", "first_word_matches", "suffix_matches", "district_matches",
    "isbe_last_name", "isbe_first_name", "isbe_district_raw",
]


def main():
    proposals = pd.read_csv(PROPOSALS_PATH, dtype=str, keep_default_na=False)

    strong = pd.Series(True, index=proposals.index)
    for column, required_value in STRONG_ROW_RULE.items():
        strong &= proposals[column] == required_value
    proposals["strong_rule_met"] = strong

    strong_count = proposals.groupby("candidate_id")["strong_rule_met"].transform("sum")
    proposals["review_group"] = "3_no_strong"
    proposals.loc[strong_count == 1, "review_group"] = "1_single_strong"
    proposals.loc[strong_count >= 2, "review_group"] = "2_multiple_strong"

    status_date = pd.to_datetime(proposals["committee_status_date"], errors="coerce")
    proposals["closed_after_flag_date"] = (
        (proposals["committee_status"] == "F") & (status_date >= pd.Timestamp(CLOSED_AFTER_DATE_TO_FLAG))
    )

    # Carry over anything already marked in an existing review sheet.
    for column in REVIEW_INPUT_COLUMNS:
        proposals[column] = ""
    carried_over = 0
    orphaned = pd.DataFrame()
    if REVIEW_PATH.exists():
        previous = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)
        marked = previous[(previous[REVIEW_INPUT_COLUMNS] != "").any(axis=1)]
        marked_by_key = marked.set_index(REVIEW_KEY_COLUMNS)[REVIEW_INPUT_COLUMNS]
        proposal_keys = proposals.set_index(REVIEW_KEY_COLUMNS).index
        for row_position, key in enumerate(proposal_keys):
            if key in marked_by_key.index:
                values = marked_by_key.loc[key]
                if isinstance(values, pd.DataFrame):  # duplicate keys: keep the first
                    values = values.iloc[0]
                for column in REVIEW_INPUT_COLUMNS:
                    proposals.iat[row_position, proposals.columns.get_loc(column)] = values[column]
                carried_over += 1
        orphaned = marked[~marked.set_index(REVIEW_KEY_COLUMNS).index.isin(proposal_keys)].copy()
        orphaned["review_group"] = "0_no_longer_proposed"

    proposals = proposals.sort_values(
        ["review_group", "candidate_id", "strong_rule_met", "evidence_source", "committee_id"],
        ascending=[True, True, False, True, True],
    )
    other_columns = [column for column in proposals.columns if column not in LEADING_COLUMNS]
    review = pd.concat([proposals[LEADING_COLUMNS + other_columns], orphaned], ignore_index=True)
    review = review.reindex(columns=LEADING_COLUMNS + other_columns).fillna("")
    review.to_csv(REVIEW_PATH, index=False)

    candidates_per_group = proposals.groupby("review_group")["candidate_id"].nunique()
    print("candidates per review group:")
    for group, count in candidates_per_group.items():
        print(f"  {group}: {count} candidates, {int((proposals['review_group'] == group).sum())} rows")
    print(f"closed committees flagged (status date >= {CLOSED_AFTER_DATE_TO_FLAG}): "
          f"{int(proposals['closed_after_flag_date'].sum())} rows")
    print(f"marks carried over from the previous sheet: {carried_over}; "
          f"marked rows no longer proposed: {len(orphaned)}")
    print(f"wrote {REVIEW_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
