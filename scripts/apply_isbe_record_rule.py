"""Mark the clear cases in the CBOE candidate -> ISBE record review sheet by rule;
leave judgment calls blank.

Input/output: data/crosswalk/candidate_isbe_review.csv (scripts/build_isbe_record_review.py)

Rule marks are recomputed on every run: rows with reviewed_by == RULE_REVIEWER_LABEL
are cleared first, then the rule is applied to every row whose `accept` is blank.
Rows marked by a person or agent are never changed.

Each open row gets `rule_outcome` and `rule_reason`, checked in this order:
  judgment_call  shared_with_other_candidate  would be accepted, but the same ISBE record would
                                              also be accepted for another CBOE candidate
                                              (duplicate filings: Ward 24 Scott, Ward 39 Nugent)
  accept_yes     all_match                    every column in ACCEPT_WHEN_ALL_TRUE is True
  accept_no      first_name_and_district_differ  every column in REJECT_WHEN_ALL_FALSE is False
                                              (same surname, different person — user chose this
                                              rule 2026-10-27; 156 of 300 rows that day)
  judgment_call  isbe_district_has_no_number  first name + suffix match; ISBE district is just
                                              "Chicago" (13 rows 2026-10-27, mostly 2027 challengers)
                 district_differs             first name + suffix match; maybe a pre-2023 ward number
                 first_name_differs           district matches; nickname (Bill/William) or a relative
                 suffix_differs               Jr / Sr / II / III differs (Burnett Jr vs his son)
                 other                        any other combination

Process for judgment calls: docs/process_committee_review.md.

Usage:
  python scripts/apply_isbe_record_rule.py
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_isbe_review.csv"

# v1 was the per-committee rule (scripts/apply_review_rule.py, retired 2026-10-27).
RULE_REVIEWER_LABEL = "rule_v2"

# Accept: ISBE ward/district number, first name word, and Jr/Sr/II/III all match
# the ballot name (columns computed in scripts/propose_committee_matches.py).
ACCEPT_WHEN_ALL_TRUE = ["district_matches", "first_word_matches", "suffix_matches"]

# Reject: both the ward/district number and the first name word differ.
REJECT_WHEN_ALL_FALSE = ["district_matches", "first_word_matches"]


def rule_outcome(row):
    """(outcome, reason) for one open row, before the shared-record check."""
    if all(row[column] == "True" for column in ACCEPT_WHEN_ALL_TRUE):
        return "accept_yes", "all_match"
    if all(row[column] == "False" for column in REJECT_WHEN_ALL_FALSE):
        return "accept_no", "first_name_and_district_differ"
    if row["suffix_matches"] == "False" and row["first_word_matches"] == "True":
        return "judgment_call", "suffix_differs"
    if row["district_matches"] == "False" and row["isbe_district_number"] == "":
        return "judgment_call", "isbe_district_has_no_number"
    if row["district_matches"] == "False":
        return "judgment_call", "district_differs"
    if row["first_word_matches"] == "False":
        return "judgment_call", "first_name_differs"
    return "judgment_call", "other"


def main():
    review = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)

    # Clear the rule's own earlier marks so they are recomputed from scratch.
    previous_rule_rows = review["reviewed_by"] == RULE_REVIEWER_LABEL
    review.loc[previous_rule_rows, ["accept", "reviewed_by"]] = ""
    still_proposed = review["rule_outcome"] != "no_longer_proposed"
    review.loc[still_proposed, ["rule_outcome", "rule_reason"]] = ""

    open_rows = still_proposed & (review["accept"].str.strip() == "")
    print(f"rows marked by a person/agent (left alone): {int((still_proposed & ~open_rows).sum())}")
    outcomes = review[open_rows].apply(rule_outcome, axis=1, result_type="expand")
    review.loc[open_rows, "rule_outcome"] = outcomes[0]
    review.loc[open_rows, "rule_reason"] = outcomes[1]

    # Would-be accepts of an ISBE record that another candidate would also get
    # (counting rule and human accepts alike).
    tentative_yes = open_rows & (review["rule_outcome"] == "accept_yes")
    human_yes = ~open_rows & still_proposed & review["accept"].str.strip().str.lower().isin({"yes", "y"})
    candidates_per_record = review[tentative_yes | human_yes].groupby("isbe_candidate_id")["candidate_id"].nunique()
    shared_records = set(candidates_per_record[candidates_per_record > 1].index)
    shared = tentative_yes & review["isbe_candidate_id"].isin(shared_records)
    review.loc[shared, ["rule_outcome", "rule_reason"]] = ["judgment_call", "shared_with_other_candidate"]

    yes_rows = open_rows & (review["rule_outcome"] == "accept_yes")
    no_rows = open_rows & (review["rule_outcome"] == "accept_no")
    review.loc[yes_rows, ["accept", "reviewed_by"]] = ["yes", RULE_REVIEWER_LABEL]
    review.loc[no_rows, ["accept", "reviewed_by"]] = ["no", RULE_REVIEWER_LABEL]
    review.to_csv(REVIEW_PATH, index=False)

    judgment = review[open_rows & (review["rule_outcome"] == "judgment_call")]
    print(f"rule accepted: {int(yes_rows.sum())} rows; rule rejected: {int(no_rows.sum())} rows")
    print(f"judgment calls left blank: {len(judgment)} rows for {judgment['candidate_id'].nunique()} candidates")
    for reason, group in judgment.groupby("rule_reason"):
        print(f"  {reason}: {len(group)} rows, {group['candidate_id'].nunique()} candidates")
    print(f"wrote {REVIEW_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
