"""Donor mix per candidate: where the money comes from and how spread out it is (PLAN.md §3).

Built on top of scripts/build_finance_tables.py — same committees, same reports, same money
windows. Run `make finance` first: this script reads its finance_reports.csv (which reports are
used) instead of re-deciding that, and imports its FINANCE_CHOICES constants.

Inputs:
  data/crosswalk/candidate_committee.csv        candidate_sum committees only (slates left out,
                                                 as in finance_summary.csv)
  data/tables/finance_reports.csv               D-2 totals + used / not used (make finance)
  data/raw/isbe/Receipts.txt                    itemized receipts on the used reports
  data/raw/isbe/Committees.txt                  type of a donor committee (name join)
Outputs:
  data/tables/donor_mix.csv                     one row per candidate x money window; every
                                                 donor-identity rule side by side (column suffix)
  data/tables/donor_mix_committee_types.csv     transfers in, by the giving committee's ISBE type
  data/tables/top_donors.csv                    the TOP_DONOR_COUNT biggest donors per candidate x
                                                 window, the same donors as the top-10 share figure;
                                                 public fields only (TOP_DONOR_PUBLIC_FIELDS)
  data/private/donor_mix_receipts.csv           every itemized receipt behind the numbers, with
                                                 its tags. GITIGNORED: donor names and addresses
                                                 (publishing donor-level rows: default no, PLAN.md)

Two layers of numbers:
  1. From D-2 totals (covers small gifts that are never itemized): money by D-2 part.
  2. From itemized receipts (gifts over the itemization threshold only): donor types, unique
     donors, concentration, geography. The script prints how itemized receipts reconcile with
     the D-2 itemized totals, per candidate, so gaps are visible.

Usage:
  python scripts/build_donor_mix.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_finance_tables import (  # noqa: E402  (same FINANCE_CHOICES as the finance tables)
    CROSSWALK_PATH, IN_KIND_PART, LOAN_PART, MONEY_WINDOWS, RECEIPTS_CHUNK_ROWS, REPORTS_OUTPUT_PATH,
    TABLES_DIR, TRANSFER_IN_PART, committee_name_key, own_committee_flags, read_isbe)
from names import normalize_name  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIR = REPO_ROOT / "data" / "private"          # gitignored
DONOR_MIX_OUTPUT_PATH = TABLES_DIR / "donor_mix.csv"
COMMITTEE_TYPES_OUTPUT_PATH = TABLES_DIR / "donor_mix_committee_types.csv"
RECEIPTS_OUTPUT_PATH = PRIVATE_DIR / "donor_mix_receipts.csv"

# Remaining Receipts.D2Part codes (transfer / loan / in-kind codes come from build_finance_tables).
INDIVIDUAL_PART = "1A"
OTHER_RECEIPT_PART = "4A"

# ----- Layer 1: D-2 totals by part --------------------------------------------
# Each mix line = D2Totals columns added together (I = itemized, NI = not itemized).
D2_MIX_LINES = {
    "individual_itemized": ["IndivContribI"],
    "individual_not_itemized": ["IndivContribNI"],     # small-dollar proxy (under the threshold)
    "transfers_in": ["XferInI", "XferInNI"],           # own-committee transfers subtracted below
    "other_receipts": ["OtherRctI", "OtherRctNI"],
    "loans": ["LoanRcvI", "LoanRcvNI"],
    "in_kind": ["TotalInKind"],
}
# Lines whose dollars make up "raised" (same as build_finance_tables RAISED_COLUMNS).
RAISED_LINES = ["individual_itemized", "individual_not_itemized", "transfers_in", "other_receipts"]

# OPEN QUESTION: denominator for the "_pct" columns. Now: all six lines above (raised + loans +
# in-kind), own-committee transfers left out. Alternative "raised_lines_only" would make
# loans / in-kind percentages meaningless, so they'd be blank. User to choose.
MIX_PERCENT_DENOMINATOR = "all_d2_lines"

# ----- Layer 2: itemized receipts ------------------------------------------------
# Donor type of each itemized receipt: first rule that matches wins (order matters).
# OPEN QUESTION (PLAN.md): do businesses / unions land in part 1A with a blank FirstName, or
# in 4A? The script prints blank-FirstName counts by part so this can be checked before
# trusting "organization".
DONOR_TYPE_RULES = [
    # (donor_type, D2Part, FirstName must be: "nonblank" / "blank" / "any")
    ("person", INDIVIDUAL_PART, "nonblank"),
    ("organization", INDIVIDUAL_PART, "blank"),
    ("committee_transfer", TRANSFER_IN_PART, "any"),
    ("loan", LOAN_PART, "any"),
    ("other_receipt", OTHER_RECEIPT_PART, "any"),
    ("in_kind", IN_KIND_PART, "any"),
]

# Which receipts count as gifts from donors (unique donors, concentration, geography).
# These are the itemized parts of "raised"; loans and in-kind are left out, as in raised.
# Own-committee transfers (build_finance_tables COMMITTEE_NAME_MATCH) are always left out:
# that is the candidate moving their own money, not a donor.
DONOR_TYPES_COUNTED = ["person", "organization", "committee_transfer", "other_receipt"]

# Unique-donor identity rules, side by side (user decision 2026-11-04). Headline first.
# Name parts are uppercased with punctuation runs -> one space (committee_name_key);
# zip = first 5 digits; address1 normalized the same way as names.
DONOR_IDENTITY_RULES = {
    "last_first_zip": ["last_key", "first_key", "zip5"],
    "last_first": ["last_key", "first_key"],
    "last_first_address1": ["last_key", "first_key", "address1_key"],
}
HEADLINE_IDENTITY_RULE = "last_first_zip"

# Concentration: share of itemized donor dollars from the N biggest donors (per identity rule).
TOP_DONOR_COUNT = 10

# Top-donor list for the dashboard (user, 2026-11-12: list the top donors, link to Illinois
# Sunshine for the full list). Same donors, rule and count as the top-10 share above
# (HEADLINE_IDENTITY_RULE), so the list adds up to that share's dollars.
TOP_DONORS_OUTPUT_PATH = TABLES_DIR / "top_donors.csv"
# Fields published per donor. Street address is left out on purpose (it stays in data/private/).
# Spelling shown: the name, city, employer and occupation on the donor's largest receipt
# (TOP_DONOR_NAME_SPELLING); a donor's receipts can spell these differently.
TOP_DONOR_PUBLIC_FIELDS = ["donor_name", "donor_type", "city", "state", "employer", "occupation"]
TOP_DONOR_NAME_SPELLING = "from_largest_receipt"
# Ties at the cutoff: donors with equal totals are ordered by name, then the first
# TOP_DONOR_COUNT are kept (same dollar total as the share figure either way).

# OPEN QUESTION: median / mean gift computed over receipt rows of these donor types only.
# Now: people only (a "typical individual gift"); organizations and committees give larger,
# fewer gifts and would pull the figure around.
GIFT_STATISTIC_DONOR_TYPES = ["person"]

# Geography of itemized donor dollars. Three Chicago rules, all written to donor_mix.csv:
#   chicago_by_city          the City field says CHICAGO
#   chicago_by_zip           the zip starts with one of CHICAGO_ZIP_PREFIXES
#   chicago_by_city_or_zip   either one (user, 2026-11-15: "a Chicago address or zip code"; the one shown on
#                            the page, see build_display_tables.DONOR_MIX_COLUMNS)
# OPEN QUESTION: 606xx misses a few Chicago zips (60707, 60827 are partly Chicago) and
# includes none outside; the City field is free text typed by the committee.
CHICAGO_CITY_NAMES = {"CHICAGO"}
CHICAGO_ZIP_PREFIXES = ("606",)
HOME_STATE = "IL"

# Self / family loans: loan rows whose lender last name equals the candidate's last name
# (last word of the normalized ballot name, scripts/names.py). A flag only, never netted.
SELF_LOAN_MATCH = "lender_last_name_equals_candidate_last_word"

# Committee transfers: the giving committee's name (LastOnlyName + FirstName, as in
# build_finance_tables) is matched to Committees.txt Name, exact after committee_name_key.
# 0 matches -> "unmatched"; 2+ matches with different types -> "ambiguous".
# Note ~55% of committees have a blank TypeOfCommittee (HANDOFF.md) -> "blank_type".
DONOR_COMMITTEE_NAME_MATCH = "exact_after_uppercase_and_punctuation_to_space"

# NOT BUILT YET: lobbyist overlay (Chicago portal p9p7-vfqc not pulled; PLAN.md step 5).

# ---------------------------------------------------------------------------

RECEIPT_COLUMNS = ["ID", "CommitteeID", "FiledDocID", "LastOnlyName", "FirstName", "RcvDate", "Amount",
                   "Occupation", "Employer", "Address1", "City", "State", "Zip", "D2Part", "Archived"]


def text_key(value):
    """Uppercase, punctuation runs -> one space (same as committee_name_key)."""
    return committee_name_key(value)


def windows_by_document(reports):
    """For each money window, the set of FiledDocIDs whose report is used and wholly inside it
    (same rule as build_finance_tables.window_figures: report_period_inside_window)."""
    used = reports[reports["used"] == "True"].copy()
    used["period_begin"] = pd.to_datetime(used["RptPdBegDate"], errors="coerce")
    used["period_end"] = pd.to_datetime(used["RptPdEndDate"], errors="coerce")
    documents = {}
    for window_name, (first_day, last_day) in MONEY_WINDOWS.items():
        inside = used[(used["period_begin"] >= pd.Timestamp(first_day))
                      & (used["period_end"] <= pd.Timestamp(last_day))]
        documents[window_name] = inside
    return documents


def load_receipts(committee_ids, document_ids):
    """Unarchived itemized receipts of these committees on these reports."""
    chunks = []
    for chunk in read_isbe("Receipts.txt", usecols=RECEIPT_COLUMNS, chunksize=RECEIPTS_CHUNK_ROWS):
        keep = (chunk["CommitteeID"].isin(committee_ids) & chunk["FiledDocID"].isin(document_ids)
                & (chunk["Archived"] == "False"))
        chunks.append(chunk[keep])
    receipts = pd.concat(chunks, ignore_index=True)
    receipts["amount"] = pd.to_numeric(receipts["Amount"], errors="coerce").fillna(0)
    receipts["received"] = pd.to_datetime(receipts["RcvDate"], errors="coerce")
    receipts["donor_name_key"] = (receipts["LastOnlyName"] + " " + receipts["FirstName"]).map(committee_name_key)
    receipts["last_key"] = receipts["LastOnlyName"].map(text_key)
    receipts["first_key"] = receipts["FirstName"].map(text_key)
    receipts["zip5"] = receipts["Zip"].str.extract(r"(\d{5})", expand=False).fillna("")
    receipts["address1_key"] = receipts["Address1"].map(text_key)
    return receipts


def tag_donor_type(receipts):
    """Apply DONOR_TYPE_RULES in order; unmatched parts -> 'unknown_part'."""
    donor_type = pd.Series("unknown_part", index=receipts.index)
    assigned = pd.Series(False, index=receipts.index)
    first_blank = receipts["FirstName"].str.strip() == ""
    for type_name, part, first_name_rule in DONOR_TYPE_RULES:
        matches = receipts["D2Part"] == part
        if first_name_rule == "blank":
            matches &= first_blank
        elif first_name_rule == "nonblank":
            matches &= ~first_blank
        newly = matches & ~assigned
        donor_type[newly] = type_name
        assigned |= newly
    return donor_type


def donor_committee_types(receipts):
    """ISBE type of the giving committee for each transfer-in receipt (DONOR_COMMITTEE_NAME_MATCH)."""
    committees = read_isbe("Committees.txt", usecols=["ID", "Name", "TypeOfCommittee"])
    committees["name_key"] = committees["Name"].map(committee_name_key)
    committees["type"] = committees["TypeOfCommittee"].str.strip().replace("", "blank_type")
    types_by_name = committees.groupby("name_key")["type"].agg(lambda types: sorted(set(types)))
    ids_by_name = committees.groupby("name_key")["ID"].agg("; ".join)

    def label(name_key):
        types = types_by_name.get(name_key)
        if types is None:
            return "unmatched"
        return types[0] if len(types) == 1 else "ambiguous"

    is_transfer = receipts["donor_type"] == "committee_transfer"
    receipts["donor_committee_type"] = ""
    receipts["donor_committee_ids"] = ""
    receipts.loc[is_transfer, "donor_committee_type"] = receipts.loc[is_transfer, "donor_name_key"].map(label)
    receipts.loc[is_transfer, "donor_committee_ids"] = (
        receipts.loc[is_transfer, "donor_name_key"].map(ids_by_name).fillna(""))
    return receipts


def share(part, whole):
    """part / whole, blank when whole is 0."""
    return part / whole if whole else None


def d2_mix(window_reports, candidate_committees, own_by_candidate):
    """Layer 1 for one window: per candidate, dollars by D-2 line, own transfers taken out."""
    rows = []
    for candidate_id, committees in candidate_committees.groupby("candidate_id"):
        reports = window_reports[window_reports["CommitteeID"].isin(set(committees["committee_id"]))]
        row = {"candidate_id": candidate_id, "d2_reports": len(reports)}
        for line, columns in D2_MIX_LINES.items():
            # float(): an empty frame of strings would otherwise sum to "" (no reports in window).
            row[line] = float(reports[columns].apply(pd.to_numeric, errors="coerce").fillna(0).astype(float).sum().sum())
        row["own_committee_transfers_in"] = own_by_candidate.get(candidate_id, 0.0)
        row["transfers_in"] -= row["own_committee_transfers_in"]
        row["raised"] = sum(row[line] for line in RAISED_LINES)
        denominator = sum(row[line] for line in D2_MIX_LINES)
        for line in D2_MIX_LINES:
            row[f"{line}_pct"] = share(row[line], denominator)
        if not len(reports):
            # No report in this window: blank, not $0 (same as finance_summary.csv).
            row.update({key: None for key in row if key not in {"candidate_id", "d2_reports"}})
        rows.append(row)
    return pd.DataFrame(rows)


def top_donors(window_receipts, window_name):
    """The TOP_DONOR_COUNT biggest donors per candidate in one window: same donor set
    (DONOR_TYPES_COUNTED, own-committee transfers out) and identity rule as receipt_metrics."""
    key_columns = DONOR_IDENTITY_RULES[HEADLINE_IDENTITY_RULE]
    donors = window_receipts[window_receipts["donor_type"].isin(DONOR_TYPES_COUNTED)
                             & ~window_receipts["own_committee_transfer"]]
    rows = []
    for candidate_id, receipts in donors.groupby("candidate_id"):
        grouped = receipts.groupby(key_columns)
        totals = grouped["amount"].agg(["sum", "count"]).reset_index()
        # TOP_DONOR_NAME_SPELLING: fields from each donor's largest receipt.
        largest = receipts.sort_values("amount", ascending=False).drop_duplicates(key_columns)
        totals = totals.merge(largest, on=key_columns, how="left")
        totals["donor_name"] = (totals["FirstName"].str.strip() + " " + totals["LastOnlyName"].str.strip()).str.strip()
        totals = totals.sort_values(["sum", "donor_name"], ascending=[False, True]).head(TOP_DONOR_COUNT)
        for rank, donor in enumerate(totals.itertuples(), start=1):
            rows.append({"candidate_id": candidate_id, "window": window_name, "rank": rank,
                         "donor_name": donor.donor_name, "donor_type": donor.donor_type,
                         "city": donor.City.strip(), "state": donor.State.strip(),
                         "employer": donor.Employer.strip(), "occupation": donor.Occupation.strip(),
                         "total": round(donor.sum, 2), "receipts": donor.count})
    return pd.DataFrame(rows, columns=["candidate_id", "window", "rank", *TOP_DONOR_PUBLIC_FIELDS, "total", "receipts"])


def receipt_metrics(window_receipts, raised_by_candidate):
    """Layer 2 for one window: per candidate, donor types / unique donors / concentration / geography."""
    rows = []
    for candidate_id, receipts in window_receipts.groupby("candidate_id"):
        donors = receipts[receipts["donor_type"].isin(DONOR_TYPES_COUNTED) & ~receipts["own_committee_transfer"]]
        donor_dollars = donors["amount"].sum()
        row = {"candidate_id": candidate_id,
               "itemized_donor_rows": len(donors),
               "itemized_donor_dollars": donor_dollars}
        for type_name in DONOR_TYPES_COUNTED:
            row[f"{type_name}_dollars"] = donors.loc[donors["donor_type"] == type_name, "amount"].sum()
        for rule_name, key_columns in DONOR_IDENTITY_RULES.items():
            totals = donors.groupby(key_columns)["amount"].sum().sort_values(ascending=False)
            row[f"unique_donors__{rule_name}"] = len(totals)
            row[f"unique_people__{rule_name}"] = donors[donors["donor_type"] == "person"].groupby(
                key_columns).ngroups
            top = totals.head(TOP_DONOR_COUNT).sum()
            row[f"top{TOP_DONOR_COUNT}_share_of_itemized__{rule_name}"] = share(top, donor_dollars)
            row[f"top{TOP_DONOR_COUNT}_share_of_raised__{rule_name}"] = share(
                top, raised_by_candidate.get(candidate_id, 0.0))
        gifts = donors.loc[donors["donor_type"].isin(GIFT_STATISTIC_DONOR_TYPES), "amount"]
        row["median_gift"] = gifts.median() if len(gifts) else None
        row["mean_gift"] = gifts.mean() if len(gifts) else None
        row["chicago_by_city_dollars"] = donors.loc[donors["in_chicago_by_city"], "amount"].sum()
        row["chicago_by_zip_dollars"] = donors.loc[donors["in_chicago_by_zip"], "amount"].sum()
        row["chicago_by_city_or_zip_dollars"] = donors.loc[
            donors["in_chicago_by_city"] | donors["in_chicago_by_zip"], "amount"].sum()
        row["out_of_state_dollars"] = donors.loc[donors["out_of_state"], "amount"].sum()
        row["state_blank_dollars"] = donors.loc[donors["State"].str.strip() == "", "amount"].sum()
        for column in ["chicago_by_city", "chicago_by_zip", "chicago_by_city_or_zip", "out_of_state"]:
            row[f"{column}_share"] = share(row[f"{column}_dollars"], donor_dollars)
        loans = receipts[receipts["donor_type"] == "loan"]
        row["loan_rows"] = len(loans)
        row["self_or_family_loan_dollars"] = loans.loc[loans["self_or_family_loan"], "amount"].sum()
        row["unknown_part_rows"] = int((receipts["donor_type"] == "unknown_part").sum())
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    crosswalk = pd.read_csv(CROSSWALK_PATH, dtype=str, keep_default_na=False)
    candidate_committees = crosswalk[crosswalk["counts_toward"] == "candidate_sum"]
    committee_ids = set(candidate_committees["committee_id"])
    reports = pd.read_csv(REPORTS_OUTPUT_PATH, dtype=str, keep_default_na=False)
    window_reports = windows_by_document(reports)
    all_documents = set().union(*(set(frame["FiledDocID"]) for frame in window_reports.values()))
    print(f"candidate_sum rows: {len(candidate_committees)}, committees: {len(committee_ids)}; "
          f"used reports in any window: {len(all_documents)}")

    receipts = load_receipts(committee_ids, all_documents)
    # A committee is candidate_sum for exactly one candidate (2+ would make it a slate).
    receipts = receipts.merge(candidate_committees[["committee_id", "candidate_id", "ballot_name_raw"]],
                              left_on="CommitteeID", right_on="committee_id", how="inner")
    receipts["donor_type"] = tag_donor_type(receipts)

    print("check for the D2Part OPEN QUESTION — itemized rows by part, blank FirstName vs not:")
    blank = receipts["FirstName"].str.strip() == ""
    print(pd.crosstab(receipts["D2Part"], blank.map({True: "first_blank", False: "first_nonblank"})).to_string())

    own = own_committee_flags(receipts[receipts["D2Part"] == TRANSFER_IN_PART], candidate_committees)
    receipts["own_committee_transfer"] = receipts["ID"].isin(set(own["ID"]))
    receipts = donor_committee_types(receipts)

    receipts["in_chicago_by_city"] = receipts["City"].map(text_key).isin(CHICAGO_CITY_NAMES)
    receipts["in_chicago_by_zip"] = receipts["zip5"].str.startswith(CHICAGO_ZIP_PREFIXES)
    state = receipts["State"].str.strip().str.upper()
    receipts["out_of_state"] = (state != "") & (state != HOME_STATE)
    candidate_last_word = receipts["ballot_name_raw"].map(lambda name: normalize_name(name).split()[-1])
    receipts["self_or_family_loan"] = (receipts["donor_type"] == "loan") & (
        receipts["last_key"] == candidate_last_word)

    for window_name, frame in window_reports.items():
        receipts[f"in_{window_name}"] = receipts["FiledDocID"].isin(set(frame["FiledDocID"]))

    mix_rows, type_rows, top_donor_rows = [], [], []
    for window_name, frame in window_reports.items():
        in_window = receipts[receipts[f"in_{window_name}"]]
        own_by_candidate = in_window[in_window["own_committee_transfer"]].groupby("candidate_id")["amount"].sum()
        layer_one = d2_mix(frame, candidate_committees, own_by_candidate)
        raised = layer_one.set_index("candidate_id")["raised"]
        layer_two = receipt_metrics(in_window, raised)
        combined = layer_one.merge(layer_two, on="candidate_id", how="left")
        combined.insert(1, "window", window_name)

        # Reconciliation: itemized donor receipts vs D-2 itemized totals of the same parts.
        d2_itemized = frame.assign(itemized=frame[["IndivContribI", "XferInI", "OtherRctI"]].apply(
            pd.to_numeric, errors="coerce").fillna(0).sum(axis=1))
        committee_to_candidate = candidate_committees.set_index("committee_id")["candidate_id"]
        d2_itemized["candidate_id"] = d2_itemized["CommitteeID"].map(committee_to_candidate)
        d2_by_candidate = d2_itemized.groupby("candidate_id")["itemized"].sum().sub(own_by_candidate, fill_value=0)
        combined["d2_itemized_minus_own_transfers"] = combined["candidate_id"].map(d2_by_candidate).fillna(0)
        combined["itemized_reconciliation_gap"] = (
            combined["d2_itemized_minus_own_transfers"] - combined["itemized_donor_dollars"].fillna(0))
        gaps = combined[combined["itemized_reconciliation_gap"].abs() > 0.01]
        print(f"{window_name}: {len(combined)} candidates; itemized receipts differ from D-2 itemized "
              f"totals for {len(gaps)} (largest gaps below)")
        for row in gaps.reindex(gaps["itemized_reconciliation_gap"].abs().sort_values(
                ascending=False).index).head(8).itertuples():
            print(f"    {row.candidate_id}: D-2 ${row.d2_itemized_minus_own_transfers:,.2f} vs receipts "
                  f"${row.itemized_donor_dollars:,.2f} (gap ${row.itemized_reconciliation_gap:,.2f})")
        mix_rows.append(combined)
        top_donor_rows.append(top_donors(in_window, window_name))

        transfers = in_window[(in_window["donor_type"] == "committee_transfer") & ~in_window["own_committee_transfer"]]
        by_type = transfers.groupby(["candidate_id", "donor_committee_type"])["amount"].agg(["sum", "count"])
        type_rows.append(by_type.reset_index().assign(window=window_name))

    candidates = candidate_committees.drop_duplicates("candidate_id")[
        ["candidate_id", "office_code", "district_number", "ballot_name_raw"]]
    donor_mix = candidates.merge(pd.concat(mix_rows, ignore_index=True), on="candidate_id", how="left")
    donor_mix.sort_values(["candidate_id", "window"]).to_csv(DONOR_MIX_OUTPUT_PATH, index=False)

    committee_types = pd.concat(type_rows, ignore_index=True).rename(
        columns={"sum": "dollars", "count": "receipt_rows"})
    committee_types[["candidate_id", "window", "donor_committee_type", "dollars", "receipt_rows"]].to_csv(
        COMMITTEE_TYPES_OUTPUT_PATH, index=False)
    print("transfers in by giving-committee type (all candidates, since_2023_07_01):")
    print(committee_types[committee_types["window"] == "since_2023_07_01"].groupby(
        "donor_committee_type")[["dollars", "receipt_rows"]].sum().to_string())

    top = pd.concat(top_donor_rows, ignore_index=True)
    top.to_csv(TOP_DONORS_OUTPUT_PATH, index=False)
    print(f"top donors: {len(top)} rows for {top['candidate_id'].nunique()} candidates "
          f"(TOP_DONOR_COUNT={TOP_DONOR_COUNT}, rule {HEADLINE_IDENTITY_RULE})")

    receipt_output_columns = (["candidate_id", "CommitteeID", "FiledDocID", "ID", "RcvDate", "Amount", "D2Part",
                               "donor_type", "own_committee_transfer", "LastOnlyName", "FirstName", "Address1",
                               "City", "State", "Zip", "Employer", "Occupation", "donor_committee_type",
                               "donor_committee_ids", "in_chicago_by_city", "in_chicago_by_zip", "out_of_state",
                               "self_or_family_loan"] + [f"in_{window}" for window in MONEY_WINDOWS])
    receipts[receipt_output_columns].sort_values(["candidate_id", "RcvDate"]).to_csv(RECEIPTS_OUTPUT_PATH, index=False)

    print(f"settings: MIX_PERCENT_DENOMINATOR={MIX_PERCENT_DENOMINATOR}, HEADLINE_IDENTITY_RULE="
          f"{HEADLINE_IDENTITY_RULE}, TOP_DONOR_COUNT={TOP_DONOR_COUNT}, GIFT_STATISTIC_DONOR_TYPES="
          f"{GIFT_STATISTIC_DONOR_TYPES}, SELF_LOAN_MATCH={SELF_LOAN_MATCH}, "
          f"DONOR_COMMITTEE_NAME_MATCH={DONOR_COMMITTEE_NAME_MATCH}")
    for path in [DONOR_MIX_OUTPUT_PATH, COMMITTEE_TYPES_OUTPUT_PATH, TOP_DONORS_OUTPUT_PATH, RECEIPTS_OUTPUT_PATH]:
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
