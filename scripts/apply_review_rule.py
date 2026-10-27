"""Mark the clear cases in the committee review sheet by rule; leave judgment calls blank.

Input/output: data/crosswalk/candidate_committee_review.csv (scripts/build_committee_review.py)

Rule marks are recomputed on every run: rows with reviewed_by == RULE_REVIEWER_LABEL
are cleared first, then the rule is applied to every row whose `accept` is blank.
Rows marked by a person or agent (any other reviewed_by, or an accept value with
no reviewed_by) are never changed.

Each row the rule looks at gets `rule_outcome` and `rule_reason`, checked in order:
  judgment_call  left blank for a person / agent (docs/process_committee_review.md):
    multiple_strong_rows       a strong row of a candidate with 2+ strong rows
    closed_in_cycle            closed committee flagged closed_after_flag_date, with an
                               ISBE link and matching first name (money may be in-cycle)
    name_only_evidence         committee_name_contains row (no ISBE link)
    not_candidate_type         would be accepted, but ISBE TypeOfCommittee is not in
                               AUTO_ACCEPT_COMMITTEE_TYPES (e.g. a PAC, or a slate committee)
    suffix_differs             active (or closed-in-cycle) committee, ISBE link, first name matches, but Jr / Sr /
                               II / III differs (father/son: Walter Burnett, Jr vs Walter
                               "Red" Burnett, 27th Ward). Not rejected, because ballots
                               sometimes omit a suffix ISBE has, or the reverse
    shared_with_other_candidate  would be accepted, but the same committee would also be
                               accepted for another candidate (duplicate filings such as
                               Ward 24 Scott / Ward 39 Nugent; Police District Council slates)
  accept_yes     single_strong_row: the one strong row of a candidate in 1_single_strong
                 -> accept = yes, committee_role = RULE_COMMITTEE_ROLE
  accept_no      weak_match: everything else (different first name, closed before the
                 flag date); "none" placeholder rows get the outcome but stay blank

Strong = STRONG_ROW_RULE in scripts/build_committee_review.py.

Usage:
  python scripts/apply_review_rule.py
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_review.csv"

RULE_REVIEWER_LABEL = "rule_v1"

# Only committees of these ISBE types are accepted automatically. On 2026-10-27
# the first draft of the rule accepted "Chicago Aldermanic Black Caucus PAC" for
# Walter Burnett and 6 Police District Council slate committees — all
# "Political Action" — so anything other than "Candidate" is a judgment call.
AUTO_ACCEPT_COMMITTEE_TYPES = {"Candidate"}

# Role written on rule-accepted rows. ASSUMPTION: a candidate's single strong row
# of type Candidate is their own campaign committee.
RULE_COMMITTEE_ROLE = "candidate committee"


def first_pass_outcome(row):
    """(outcome, reason) before the type and shared-committee checks."""
    if row["review_group"] == "2_multiple_strong" and row["strong_rule_met"] == "True":
        return "judgment_call", "multiple_strong_rows"
    # Checked before closed_in_cycle so a father's closed committee is labeled as a suffix question.
    if (row["evidence_source"] == "cmte_candidate_link" and row["first_word_matches"] == "True"
            and (row["committee_status"] == "A" or row["closed_after_flag_date"] == "True")
            and row["suffix_matches"] == "False"):
        return "judgment_call", "suffix_differs"
    if (row["closed_after_flag_date"] == "True" and row["evidence_source"] == "cmte_candidate_link"
            and row["first_word_matches"] == "True"):
        return "judgment_call", "closed_in_cycle"
    if row["evidence_source"] == "committee_name_contains":
        return "judgment_call", "name_only_evidence"
    if row["review_group"] == "1_single_strong" and row["strong_rule_met"] == "True":
        return "accept_yes", "single_strong_row"
    if row["evidence_source"] == "none":
        return "accept_no", "no_evidence_placeholder"
    return "accept_no", "weak_match"


def main():
    review = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)
    for column in ("rule_reason", "rule_outcome"):
        if column not in review.columns:
            review.insert(review.columns.get_loc("accept"), column, "")

    # Clear the rule's own earlier marks so they are recomputed from scratch.
    previous_rule_rows = review["reviewed_by"] == RULE_REVIEWER_LABEL
    review.loc[previous_rule_rows, ["accept", "committee_role", "reviewed_by"]] = ""
    review[["rule_outcome", "rule_reason"]] = ""

    open_rows = review["accept"].str.strip() == ""
    print(f"rows marked by a person/agent (left alone): {int((~open_rows).sum())}")
    outcomes = review[open_rows].apply(first_pass_outcome, axis=1, result_type="expand")
    review.loc[open_rows, "rule_outcome"] = outcomes[0]
    review.loc[open_rows, "rule_reason"] = outcomes[1]

    # Would-be accepts that are not plain candidate committees.
    tentative_yes = open_rows & (review["rule_outcome"] == "accept_yes")
    wrong_type = tentative_yes & ~review["committee_type"].isin(AUTO_ACCEPT_COMMITTEE_TYPES)
    review.loc[wrong_type, ["rule_outcome", "rule_reason"]] = ["judgment_call", "not_candidate_type"]

    # Would-be accepts of a committee that another candidate would also get
    # (counting rule and human accepts alike).
    tentative_yes = open_rows & (review["rule_outcome"] == "accept_yes")
    human_yes = ~open_rows & review["accept"].str.strip().str.lower().isin({"yes", "y"})
    candidates_per_committee = review[tentative_yes | human_yes].groupby("committee_id")["candidate_id"].nunique()
    shared_ids = set(candidates_per_committee[candidates_per_committee > 1].index)
    shared = tentative_yes & review["committee_id"].isin(shared_ids)
    review.loc[shared, ["rule_outcome", "rule_reason"]] = ["judgment_call", "shared_with_other_candidate"]

    yes_rows = open_rows & (review["rule_outcome"] == "accept_yes")
    no_rows = open_rows & (review["rule_outcome"] == "accept_no") & (review["rule_reason"] != "no_evidence_placeholder")
    review.loc[yes_rows, ["accept", "committee_role", "reviewed_by"]] = ["yes", RULE_COMMITTEE_ROLE, RULE_REVIEWER_LABEL]
    review.loc[no_rows, ["accept", "reviewed_by"]] = ["no", RULE_REVIEWER_LABEL]
    review.to_csv(REVIEW_PATH, index=False)

    judgment = review[open_rows & (review["rule_outcome"] == "judgment_call")]
    print(f"rule accepted: {int(yes_rows.sum())} rows; rule rejected: {int(no_rows.sum())} rows")
    print(f"judgment calls left blank: {len(judgment)} rows for {judgment['candidate_id'].nunique()} candidates")
    for reason, group in judgment.groupby("rule_reason"):
        print(f"  {reason}: {len(group)} rows, {group['candidate_id'].nunique()} candidates")
    placeholders = review["rule_reason"] == "no_evidence_placeholder"
    print(f"candidates with no evidence at all (left blank): {int(placeholders.sum())}")
    print(f"wrote {REVIEW_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
