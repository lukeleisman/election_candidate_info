"""Write the committees you accepted in the review sheet to the crosswalk.

Input:  data/crosswalk/candidate_committee_review.csv   (you mark accept = yes / no)
Output: data/crosswalk/candidate_committee.csv          (rebuilt from the sheet every run)

The review sheet is the hand-edited source; the crosswalk is regenerated from it,
so edit the sheet, not the crosswalk. One output row per (candidate, committee)
accepted — if the same committee was accepted through two evidence rows, it is
written once, with both evidence sources listed.

Checks (printed, never fixed automatically):
  - accept values other than ACCEPTED_VALUES / REJECTED_VALUES / blank
  - accepted rows with no committee_role
  - committees accepted for more than one candidate

Usage:
  python scripts/apply_committee_review.py
"""

from datetime import date
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_review.csv"
CROSSWALK_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee.csv"

# What counts as yes / no in the accept column (compared lowercased, trimmed).
ACCEPTED_VALUES = {"yes", "y"}
REJECTED_VALUES = {"no", "n"}

CROSSWALK_COLUMNS = [
    "candidate_id", "ballot_name_raw", "committee_id", "committee_name",
    "committee_role", "committee_status", "committee_status_date",
    "evidence_sources", "confirmed_by", "confirmed_on", "notes",
]


def main():
    review = pd.read_csv(REVIEW_PATH, dtype=str, keep_default_na=False)
    accept = review["accept"].str.strip().str.lower()

    unknown = review[(accept != "") & ~accept.isin(ACCEPTED_VALUES | REJECTED_VALUES)]
    if len(unknown):
        print(f"WARNING: {len(unknown)} rows with unrecognized accept values (ignored):")
        print(unknown[["candidate_id", "committee_id", "accept"]].to_string(index=False))

    accepted = review[accept.isin(ACCEPTED_VALUES)]
    rows = []
    for (candidate_id, committee_id), group in accepted.groupby(["candidate_id", "committee_id"], sort=True):
        first = group.iloc[0]
        rows.append({
            "candidate_id": candidate_id,
            "ballot_name_raw": first["ballot_name_raw"],
            "committee_id": committee_id,
            "committee_name": first["committee_name"],
            "committee_role": "; ".join(sorted(set(group["committee_role"]) - {""})),
            "committee_status": first["committee_status"],
            "committee_status_date": first["committee_status_date"],
            "evidence_sources": "; ".join(sorted(set(group["evidence_source"]))),
            "confirmed_by": "; ".join(sorted(set(group["reviewed_by"]) - {""})),
            # Date this file was rebuilt, not the date of review (the sheet has no date column).
            "confirmed_on": date.today().isoformat(),
            "notes": " | ".join(sorted(set(group["review_notes"]) - {""})),
        })
    crosswalk = pd.DataFrame(rows, columns=CROSSWALK_COLUMNS)
    crosswalk.to_csv(CROSSWALK_PATH, index=False)

    no_role = crosswalk[crosswalk["committee_role"] == ""]
    if len(no_role):
        print(f"WARNING: {len(no_role)} accepted committees have no committee_role")
    shared = crosswalk.groupby("committee_id")["candidate_id"].nunique()
    shared = shared[shared > 1]
    if len(shared):
        print(f"WARNING: committees accepted for more than one candidate: {shared.to_dict()}")

    reviewed_candidates = review.loc[accept != "", "candidate_id"].nunique()
    print(f"rows marked yes: {len(accepted)}, no: {int(accept.isin(REJECTED_VALUES).sum())}, "
          f"blank: {int((accept == '').sum())}")
    print(f"candidates with any row marked: {reviewed_candidates} of {review['candidate_id'].nunique()}")
    print(f"wrote {CROSSWALK_PATH.relative_to(REPO_ROOT)} ({len(crosswalk)} candidate-committee rows)")


if __name__ == "__main__":
    main()
