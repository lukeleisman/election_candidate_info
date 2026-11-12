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
  judgment_call  last_name_<match type>       would be accepted, but the last name matched only
                                              loosely (hyphen vs space, word order; added 2026-11-12)
  judgment_call  district_town_unknown        would be accepted, but the ISBE district is a bare number
                                              and the address is blank / redacted (added 2026-11-12)
  accept_yes     all_match                    every column in ACCEPT_WHEN_ALL_TRUE is True
  judgment_call  nickname_and_district_differ  would be rejected (next line), but the first names
                                              are nicknames of each other (Bob / Robert; table
                                              NICKNAME_GROUPS in scripts/names.py; added 2026-11-04)
  judgment_call  isbe_first_name_is_other_ballot_word  would be rejected, but the ISBE first name is a
                                              later ballot word (DONGBO MARK SU / "Mark"; 2026-11-12)
  accept_no      first_name_and_district_differ  every column in REJECT_WHEN_ALL_FALSE is False
                                              (same surname, different person — user chose this
                                              rule 2026-10-27; 156 of 300 rows that day)
  judgment_call  isbe_district_has_no_number  first name + suffix match; ISBE district is just
                                              "Chicago" (13 rows 2026-10-27, mostly 2027 challengers)
                 district_differs             first name + suffix match; maybe a pre-2023 ward number
                 first_name_is_nickname       district matches; first names are in one NICKNAME_GROUPS
                                              group (Nate / Nathaniel)
                 first_name_differs           district matches; first name differs otherwise
                                              (spelling, typo, or a relative)
                 suffix_differs               Jr / Sr / II / III differs (Burnett Jr vs his son)
                 other                        any other combination

Process for judgment calls: docs/process_committee_review.md.

Usage:
  python scripts/apply_isbe_record_rule.py
"""

from pathlib import Path

import pandas as pd

from names import first_names_equivalent, normalize_name, quoted_nicknames

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_isbe_review.csv"

# v1 was the per-committee rule (scripts/apply_review_rule.py, retired 2026-10-27).
# v2 (2026-10-27) had no nickname check; v3 (2026-11-04) adds it; v4 (2026-11-12) adds
# the loose last-name check (LOOSE_LAST_NAME_EFFECT).
# Keep RULE_REVIEWER_LABEL in step with scripts/build_isbe_record_review.py.
RULE_REVIEWER_LABEL = "rule_v4"

# Earlier rule labels: their marks are cleared and recomputed like the current
# label's, never treated as a person's mark.
RETIRED_RULE_REVIEWER_LABELS = {"rule_v2", "rule_v3"}

# Accept: ISBE ward/district number, first name word, and Jr/Sr/II/III all match
# the ballot name (columns computed in scripts/propose_committee_matches.py).
ACCEPT_WHEN_ALL_TRUE = ["district_matches", "first_word_matches", "suffix_matches"]

# Reject: both the ward/district number and the first name word differ.
REJECT_WHEN_ALL_FALSE = ["district_matches", "first_word_matches"]

# What a nickname match (scripts/names.py NICKNAME_GROUPS) does. Chosen 2026-11-04
# (user: "add the nickname table to the rule"):
#   "judgment_call_instead_of_no"  a would-be reject becomes a judgment call; a
#                                  first-name judgment call is labeled first_name_is_nickname.
#                                  The rule never accepts on a nickname.
# OPEN QUESTION (user's): also accept automatically when the nickname matches and
# district + suffix match? Not done: every such row so far was reviewed by hand.
NICKNAME_EFFECT = "judgment_call_instead_of_no"

# Last name matched only loosely (column last_name_match_type is not EXACT_LAST_NAME_MATCH_TYPE:
# hyphen vs space, or words in another order; see LOOSE_LAST_NAME_MATCHES_ON in
# scripts/propose_committee_matches.py). Chosen 2026-11-12 (user: flag for human confirmation):
#   "judgment_call_instead_of_yes"  a would-be accept becomes judgment call
#                                   last_name_<type> (e.g. last_name_word_order_differs).
#                                   Would-be rejects stay rejects (different first name AND ward).
LOOSE_LAST_NAME_EFFECT = "judgment_call_instead_of_yes"
EXACT_LAST_NAME_MATCH_TYPE = "exact_words"

# ISBE district bases where the town is not known (address blank / redacted; see
# BARE_NUMBER_DISTRICT_NO_ADDRESS_COUNTS in scripts/propose_committee_matches.py). Added
# 2026-11-12: a would-be accept becomes judgment call district_town_unknown.
UNCERTAIN_DISTRICT_BASES = {"bare_number_and_no_address"}

# Added 2026-11-12 (user: "broader rules are better than narrow, with anything fishy marked
# for manual judgment"). When the ISBE first name is a later word of the ballot name (ballot
# "DONGBO MARK SU", ISBE "Mark Su"), a would-be reject becomes judgment call
# isbe_first_name_is_other_ballot_word. False = reject as before.
OTHER_BALLOT_WORD_MAKES_JUDGMENT_CALL = True

# Also compare the ISBE first name with a quoted nickname on the ballot
# ('WILLIAM "BILL" MORTON' vs ISBE "Bill"). normalize_name drops quoted nicknames,
# so first_word_matches never sees them.
COMPARE_BALLOT_QUOTED_NICKNAME = True


def first_name_is_nickname(row):
    """True if the ballot first name (or a quoted ballot nickname) and the ISBE first
    name are equal or nicknames of each other (scripts/names.py NICKNAME_GROUPS)."""
    isbe_first = (normalize_name(row["isbe_first_name"]).split() or [""])[0]
    if not isbe_first:
        return False
    ballot_names = (normalize_name(row["ballot_name_raw"]).split() or [""])[:1]
    if COMPARE_BALLOT_QUOTED_NICKNAME:
        ballot_names += [nickname.split()[0] for nickname in quoted_nicknames(row["ballot_name_raw"])]
    return any(first_names_equivalent(ballot_name, isbe_first) for ballot_name in ballot_names if ballot_name)


def isbe_first_name_is_other_ballot_word(row):
    """True if the ISBE first name's first word is a ballot word other than the first
    ('DONGBO MARK SU' vs ISBE 'Mark')."""
    isbe_first = (normalize_name(row["isbe_first_name"]).split() or [""])[0]
    return bool(isbe_first) and isbe_first in normalize_name(row["ballot_name_raw"]).split()[1:]


def rule_outcome(row):
    """(outcome, reason) for one open row, before the shared-record check."""
    if all(row[column] == "True" for column in ACCEPT_WHEN_ALL_TRUE):
        if row["last_name_match_type"] != EXACT_LAST_NAME_MATCH_TYPE:
            return "judgment_call", f"last_name_{row['last_name_match_type']}"
        if row["isbe_district_basis"] in UNCERTAIN_DISTRICT_BASES:
            return "judgment_call", "district_town_unknown"
        return "accept_yes", "all_match"
    nickname = first_name_is_nickname(row)
    if all(row[column] == "False" for column in REJECT_WHEN_ALL_FALSE):
        if nickname:
            return "judgment_call", "nickname_and_district_differ"
        if OTHER_BALLOT_WORD_MAKES_JUDGMENT_CALL and isbe_first_name_is_other_ballot_word(row):
            return "judgment_call", "isbe_first_name_is_other_ballot_word"
        return "accept_no", "first_name_and_district_differ"
    if row["suffix_matches"] == "False" and row["first_word_matches"] == "True":
        return "judgment_call", "suffix_differs"
    if row["district_matches"] == "False" and row["isbe_district_number"] == "":
        return "judgment_call", "isbe_district_has_no_number"
    if row["district_matches"] == "False":
        return "judgment_call", "district_differs"
    if row["first_word_matches"] == "False":
        if nickname:
            return "judgment_call", "first_name_is_nickname"
        return "judgment_call", "first_name_differs"
    return "judgment_call", "other"


def main():
    review = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)

    # Clear the rule's own earlier marks so they are recomputed from scratch.
    previous_rule_rows = review["reviewed_by"].isin({RULE_REVIEWER_LABEL} | RETIRED_RULE_REVIEWER_LABELS)
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
