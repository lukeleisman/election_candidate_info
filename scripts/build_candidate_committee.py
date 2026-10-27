"""Build the candidate -> committee crosswalk: Illinois Sunshine's rule, plus the
committees it would miss. Nothing here is reviewed committee by committee
(PLAN.md §3a); the only confirmation is candidate -> ISBE record.

Inputs:
  data/crosswalk/candidate_isbe_review.csv          accept = yes rows (you + scripts/apply_isbe_record_rule.py)
  data/crosswalk/candidate_committee_proposals.csv  ISBE links + name matches (scripts/propose_committee_matches.py)
  data/crosswalk/committee_additions_manual.csv     hand / agent rows; created with a header if missing
Output:
  data/crosswalk/candidate_committee.csv            rebuilt every run — don't edit it, edit the inputs

One row per (candidate, committee). Column link_basis says how the committee was found:
  isbe_link   ISBE CmteCandidateLinks ties it to an ISBE record you accepted — any
              committee type or status, as on Illinois Sunshine (DataMade
              illinois-sunshine etl.py, SunshineCandidateCommittees)
  name_only   committee name contains the ballot first + last word (active committees
              only — NAME_SEARCH_COMMITTEE_STATUSES in propose_committee_matches.py), and
              it is not an isbe_link committee of this candidate
  manual      an "add" row in committee_additions_manual.csv
A committee found more than one way gets the first basis in LINK_BASIS_PRIORITY.

Column counts_toward (how finance tables use the row; user decisions 2026-10-27):
  candidate_sum  added into the candidate's total (every committee not below)
  slate_column   committee is in this file for 2+ candidates -> its own column, not
                 added in, because how slate money is split isn't clear
  excluded       an "exclude" row in committee_additions_manual.csv names it — the row
                 stays visible with the reason; nothing is dropped silently
Whether PACs or closed committees should count is left for later, once the user has
seen them (committee_type / committee_status columns are here for that).

Usage:
  python scripts/build_candidate_committee.py
"""

import csv
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_isbe_review.csv"
PROPOSALS_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_proposals.csv"
MANUAL_PATH = REPO_ROOT / "data" / "crosswalk" / "committee_additions_manual.csv"
CROSSWALK_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee.csv"

# What counts as yes in the review sheet's accept column (compared lowercased, trimmed).
ACCEPTED_VALUES = {"yes", "y"}

# Manual file: one row per candidate x committee.
#   action      "add" (committee belongs to the candidate) or "exclude" (an isbe_link /
#               name_only row that is plainly wrong — kept, marked excluded)
#   source_url  where the evidence is (required for "add")
MANUAL_COLUMNS = ["candidate_id", "committee_id", "action", "source_url", "entered_by", "entered_on", "notes"]
MANUAL_ACTIONS = {"add", "exclude"}

# A committee in this file for at least this many candidates is a slate committee.
SLATE_MINIMUM_CANDIDATES = 2

LINK_BASIS_PRIORITY = ["isbe_link", "name_only", "manual"]

COMMITTEE_COLUMNS = [
    "committee_name", "committee_type", "committee_status", "committee_status_date",
    "committee_creation_date",
]
CROSSWALK_COLUMNS = [
    "candidate_id", "office_code", "district_number", "ballot_name_raw", "also_filed_as",
    "committee_id", *COMMITTEE_COLUMNS,
    "link_basis", "all_link_bases", "isbe_candidate_ids",
    "counts_toward", "candidates_sharing_committee", "manual_source_url", "manual_notes",
]


def main():
    review = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)
    proposals = pd.read_csv(PROPOSALS_PATH, dtype=str, keep_default_na=False)
    if not MANUAL_PATH.exists():
        with open(MANUAL_PATH, "w", newline="") as output_file:
            csv.writer(output_file).writerow(MANUAL_COLUMNS)
        print(f"created empty {MANUAL_PATH.relative_to(REPO_ROOT)}")
    manual = pd.read_csv(MANUAL_PATH, dtype=str, keep_default_na=False)

    accepted = review[review["accept"].str.strip().str.lower().isin(ACCEPTED_VALUES)]
    accepted_pairs = set(zip(accepted["candidate_id"], accepted["isbe_candidate_id"]))
    candidate_columns = proposals.drop_duplicates("candidate_id").set_index("candidate_id")[
        ["office_code", "district_number", "ballot_name_raw", "also_filed_as"]]
    committee_info = proposals[proposals["committee_id"] != ""].drop_duplicates("committee_id").set_index(
        "committee_id")[COMMITTEE_COLUMNS]

    # 1. isbe_link: committees ISBE links to an accepted record.
    links = proposals[proposals["evidence_source"] == "cmte_candidate_link"]
    is_accepted = [pair in accepted_pairs for pair in zip(links["candidate_id"], links["isbe_candidate_id"])]
    isbe_rows = links[is_accepted][["candidate_id", "committee_id", "isbe_candidate_id"]].assign(link_basis="isbe_link")

    # 2. name_only: name matches (every one is listed here; the isbe_link ones are merged below).
    name_rows = proposals[proposals["evidence_source"] == "committee_name_contains"][
        ["candidate_id", "committee_id"]].assign(isbe_candidate_id="", link_basis="name_only")

    # 3. manual adds. Committee details come from the proposals when the committee is there.
    bad_actions = manual[~manual["action"].isin(MANUAL_ACTIONS)]
    if len(bad_actions):
        print(f"WARNING: {len(bad_actions)} manual rows with action not in {sorted(MANUAL_ACTIONS)} (ignored)")
    manual_adds = manual[manual["action"] == "add"]
    if (manual_adds["source_url"].str.strip() == "").any():
        print("WARNING: manual add rows with no source_url — kept, but add the evidence")
    manual_rows = manual_adds[["candidate_id", "committee_id"]].assign(isbe_candidate_id="", link_basis="manual")

    all_rows = pd.concat([isbe_rows, name_rows, manual_rows], ignore_index=True)
    all_rows["basis_rank"] = all_rows["link_basis"].map(LINK_BASIS_PRIORITY.index)
    rows = []
    for (candidate_id, committee_id), group in all_rows.groupby(["candidate_id", "committee_id"], sort=True):
        group = group.sort_values("basis_rank")
        rows.append({
            "candidate_id": candidate_id,
            "committee_id": committee_id,
            "link_basis": group["link_basis"].iloc[0],
            "all_link_bases": "; ".join(dict.fromkeys(group["link_basis"])),
            "isbe_candidate_ids": "; ".join(sorted(set(group["isbe_candidate_id"]) - {""})),
        })
    crosswalk = pd.DataFrame(rows)
    crosswalk = crosswalk.join(candidate_columns, on="candidate_id").join(committee_info, on="committee_id")
    missing_info = crosswalk["committee_name"].isna()
    if missing_info.any():
        print(f"NOTE: {int(missing_info.sum())} manual committees not in the proposals file — "
              f"committee details left blank: {crosswalk.loc[missing_info, 'committee_id'].tolist()}")

    # Manual exclusions (kept as rows, marked).
    exclusions = manual[manual["action"] == "exclude"].set_index(["candidate_id", "committee_id"])
    manual_by_key = manual.drop_duplicates(["candidate_id", "committee_id"]).set_index(["candidate_id", "committee_id"])
    keys = list(zip(crosswalk["candidate_id"], crosswalk["committee_id"]))
    is_excluded = pd.Series([key in exclusions.index for key in keys], index=crosswalk.index)
    crosswalk["manual_source_url"] = [manual_by_key.at[key, "source_url"] if key in manual_by_key.index else "" for key in keys]
    crosswalk["manual_notes"] = [manual_by_key.at[key, "notes"] if key in manual_by_key.index else "" for key in keys]
    unmatched_exclusions = set(exclusions.index) - set(keys)
    if unmatched_exclusions:
        print(f"WARNING: exclude rows that match no crosswalk row: {sorted(unmatched_exclusions)}")

    # Slates: committees (not excluded) in this file for 2+ candidates.
    kept = crosswalk[~is_excluded]
    candidates_by_committee = kept.groupby("committee_id")["candidate_id"].agg(lambda ids: sorted(set(ids)))
    crosswalk["candidates_sharing_committee"] = crosswalk["committee_id"].map(
        lambda committee_id: "; ".join(candidates_by_committee.get(committee_id, [])))
    is_slate = crosswalk["committee_id"].map(
        lambda committee_id: len(candidates_by_committee.get(committee_id, [])) >= SLATE_MINIMUM_CANDIDATES)
    crosswalk["counts_toward"] = "candidate_sum"
    crosswalk.loc[is_slate, "counts_toward"] = "slate_column"
    crosswalk.loc[is_excluded, "counts_toward"] = "excluded"

    crosswalk = crosswalk.reindex(columns=CROSSWALK_COLUMNS).fillna("")
    crosswalk.to_csv(CROSSWALK_PATH, index=False)

    in_scope = proposals["candidate_id"].nunique()
    print(f"accepted candidate x ISBE record pairs: {len(accepted_pairs)} "
          f"({accepted['candidate_id'].nunique()} candidates)")
    print(f"crosswalk rows by link_basis: {crosswalk['link_basis'].value_counts().to_dict()}")
    print(f"crosswalk rows by counts_toward: {crosswalk['counts_toward'].value_counts().to_dict()}")
    print(f"candidates with at least one committee: {crosswalk['candidate_id'].nunique()} of {in_scope}")
    print(f"wrote {CROSSWALK_PATH.relative_to(REPO_ROOT)} ({len(crosswalk)} rows)")


if __name__ == "__main__":
    main()
