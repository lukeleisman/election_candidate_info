"""Tables for the ward-by-ward money display (the "Chicago 2027 Candidate Money" dashboard).

Only reshapes what earlier steps computed; no new money arithmetic happens here.
Every number comes straight from a column of finance_summary.csv, finance_by_committee.csv
or donor_mix.csv (named in DISPLAY_COLUMNS_FROM below), so the display can be checked
against those files cell for cell.

Inputs:
  data/candidates/candidates_cboe.csv        every ballot filing (also candidates with no committee)
  data/candidates/duplicate_filings.csv      one person filed twice (hand-entered)
  data/tables/finance_summary.csv            make finance
  data/tables/finance_by_committee.csv       make finance
  data/tables/donor_mix.csv                  make donor-mix
Outputs (uploaded to the dashboard as attached files):
  data/tables/display_candidates.csv         one row per ballot filing in DISPLAY_OFFICE_CODES
  data/tables/display_committees.csv         one row per candidate x committee (excluded rows left out)

Usage:
  python scripts/build_display_tables.py
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
DUPLICATES_PATH = REPO_ROOT / "data" / "candidates" / "duplicate_filings.csv"
TABLES_DIR = REPO_ROOT / "data" / "tables"
FINANCE_SUMMARY_PATH = TABLES_DIR / "finance_summary.csv"
FINANCE_BY_COMMITTEE_PATH = TABLES_DIR / "finance_by_committee.csv"
DONOR_MIX_PATH = TABLES_DIR / "donor_mix.csv"
CANDIDATES_OUTPUT_PATH = TABLES_DIR / "display_candidates.csv"
COMMITTEES_OUTPUT_PATH = TABLES_DIR / "display_committees.csv"

# Offices shown. Police District Councils (PDC) are left out because the committee step
# skips them for now (COMMITTEE_STEP_OFFICE_CODES in propose_committee_matches.py).
DISPLAY_OFFICE_CODES = ["MAYOR", "CLERK", "TREAS", "ALD"]
CITYWIDE_RACE_LABELS = {"MAYOR": "Mayor", "CLERK": "City Clerk", "TREAS": "City Treasurer"}

# Money windows from build_finance_tables.MONEY_WINDOWS; the page lets the reader switch.
WINDOWS = ["since_2026_01_01", "latest_quarter", "since_2023_07_01"]

# Donor-mix figures shown, with the donor_mix.csv column each one copies. The unique-donor
# and top-10 figures use the headline identity rule (HEADLINE_IDENTITY_RULE in
# build_donor_mix.py); the other two rules stay in donor_mix.csv.
DONOR_MIX_COLUMNS = {
    "unique_donors": "unique_donors__last_first_zip",
    "not_itemized_individual_pct": "individual_not_itemized_pct",
    "top10_share_of_raised": "top10_share_of_raised__last_first_zip",
    "median_gift": "median_gift",
    "chicago_by_zip_share": "chicago_by_zip_share",
    # What Raised is made of (D-2 lines, own-committee transfers already out of transfers_in),
    # for the candidate section's breakdown (added 2026-11-12). mix_raised should equal
    # <window>_raised from finance_summary.csv; build_dashboard.py prints any difference.
    "mix_individual_itemized": "individual_itemized",
    "mix_individual_not_itemized": "individual_not_itemized",
    "mix_transfers_in": "transfers_in",
    "mix_other_receipts": "other_receipts",
    "mix_own_committee_transfers_in": "own_committee_transfers_in",
    "mix_raised": "raised",
    "mix_d2_reports": "d2_reports",
}

# Per-window finance figures shown, copied from finance_summary.csv as <window>_<name>.
FINANCE_WINDOW_COLUMNS = ["raised", "loans", "in_kind"]

# ---------------------------------------------------------------------------


def race_fields(row):
    """race_key / race_label / race_order for one candidate row."""
    if row["office_code"] == "ALD":
        ward = int(row["district_number"])
        return f"ALD-{ward:02d}", f"Ward {ward}", 100 + ward
    order = DISPLAY_OFFICE_CODES.index(row["office_code"])
    return row["office_code"], CITYWIDE_RACE_LABELS[row["office_code"]], order


def main():
    candidates = pd.read_csv(CANDIDATES_PATH, dtype=str, keep_default_na=False)
    candidates = candidates[candidates["office_code"].isin(DISPLAY_OFFICE_CODES)].copy()
    candidates[["race_key", "race_label", "race_order"]] = candidates.apply(
        lambda row: pd.Series(race_fields(row)), axis=1)

    duplicates = pd.read_csv(DUPLICATES_PATH, dtype=str, keep_default_na=False)
    candidates["duplicate_filing_of"] = candidates["candidate_id"].map(
        duplicates.set_index("candidate_id")["same_person_as"]).fillna("")

    summary = pd.read_csv(FINANCE_SUMMARY_PATH, dtype=str, keep_default_na=False).set_index("candidate_id")
    by_committee = pd.read_csv(FINANCE_BY_COMMITTEE_PATH, dtype=str, keep_default_na=False)
    donor_mix = pd.read_csv(DONOR_MIX_PATH, dtype=str, keep_default_na=False)

    output = candidates[["candidate_id", "race_key", "race_label", "race_order", "ballot_name_raw",
                         "filing_date", "duplicate_filing_of"]].copy()
    summed = by_committee[by_committee["counts_toward"] == "candidate_sum"]
    output["committees_added"] = output["candidate_id"].map(summed.groupby("candidate_id").size()).fillna(0).astype(int)
    output["name_only_committees"] = output["candidate_id"].map(
        summed[summed["link_basis"] == "name_only"].groupby("candidate_id").size()).fillna(0).astype(int)
    output["cash_on_hand"] = output["candidate_id"].map(summary["cash_on_hand"]).fillna("")
    output["a1_gifts_since_last_report"] = output["candidate_id"].map(summary["a1_gifts_since_last_report"]).fillna("")
    output["committees_cash_not_current"] = output["candidate_id"].map(
        summary["committees_cash_not_current"]).fillna("")
    output["slate_committees_not_added"] = output["candidate_id"].map(
        summary["slate_committees_not_added"]).fillna("")

    for window in WINDOWS:
        for name in FINANCE_WINDOW_COLUMNS:
            output[f"{window}_{name}"] = output["candidate_id"].map(summary[f"{window}_{name}"]).fillna("")
        mix = donor_mix[donor_mix["window"] == window].set_index("candidate_id")
        for name, source_column in DONOR_MIX_COLUMNS.items():
            output[f"{window}_{name}"] = output["candidate_id"].map(mix[source_column]).fillna("")

    output = output.sort_values(["race_order", "candidate_id"])
    output.to_csv(CANDIDATES_OUTPUT_PATH, index=False)

    committee_columns = ["candidate_id", "committee_id", "committee_name", "committee_type", "committee_status",
                         "counts_toward", "link_basis", "cash_on_hand", "cash_on_hand_report_end",
                         "a1_gifts_since_last_report"] + [f"{window}_raised" for window in WINDOWS] + [
                         # Sunshine-style total (SUNSHINE_STYLE_DOCUMENT_TYPES in build_finance_tables.py)
                         "sunshine_style_total", "sunshine_style_first_report_begin"]
    committees = by_committee[by_committee["candidate_id"].isin(set(output["candidate_id"]))][committee_columns]
    committees.to_csv(COMMITTEES_OUTPUT_PATH, index=False)

    no_committee = output[(output["committees_added"] == 0) & (output["duplicate_filing_of"] == "")]
    print(f"display_candidates: {len(output)} filings in {output['race_key'].nunique()} races; "
          f"{len(no_committee)} with no committee added; {int((output['duplicate_filing_of'] != '').sum())} "
          f"duplicate filings")
    print(f"display_committees: {len(committees)} rows")
    for path in [CANDIDATES_OUTPUT_PATH, COMMITTEES_OUTPUT_PATH]:
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
