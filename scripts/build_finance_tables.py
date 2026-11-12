"""Money per candidate from ISBE D-2 reports, for the committees in the crosswalk.

Every choice is in the FINANCE_CHOICES block below (user decisions 2026-11-04, PLAN.md §3).
Nothing here picks between sources: ISBE only. Illinois Sunshine comparison is a later step.

Inputs:
  data/crosswalk/candidate_committee.csv     (scripts/build_candidate_committee.py)
  data/raw/isbe/{FiledDocs,D2Totals,Receipts}.txt   (scripts/fetch_isbe.py)
Outputs (data/tables/, rebuilt every run):
  finance_reports.csv       raw layer: every D-2 total of every crosswalk committee, with
                            the document it came from and whether it is used (and if not, why)
  finance_by_committee.csv  one row per candidate x committee (excluded rows left out):
                            cash on hand, each money window, A-1 gifts since the last report
  finance_summary.csv       one row per candidate: the candidate_sum committees added up;
                            slate committees are named, not added (their money is in
                            finance_by_committee.csv)

How the numbers are built (all from D2Totals, which covers small unitemized gifts too):
  raised            individual contributions + transfers in + other receipts (D-2 parts 1, 2, 4),
                    itemized and not itemized, MINUS transfers in from the candidate's own
                    candidate_sum committees (those are shown in own_committee_transfers_in)
  loans             loans received (part 3) — own column, not in raised
  in_kind           in-kind contributions (part 5) — own column, not cash, not in raised
  individual_not_itemized   individual gifts not itemized (small donors) — part of raised,
                    shown alone as a small-dollar figure
  own_committee_transfers_in  itemized transfer-in receipts whose donor name matches another
                    candidate_sum committee of the same candidate (name match: see
                    COMMITTEE_NAME_MATCH below). Only itemized transfers can be matched.

Usage:
  python scripts/build_finance_tables.py
"""

import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CROSSWALK_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee.csv"
ISBE_DIR = REPO_ROOT / "data" / "raw" / "isbe"
TABLES_DIR = REPO_ROOT / "data" / "tables"
REPORTS_OUTPUT_PATH = TABLES_DIR / "finance_reports.csv"
BY_COMMITTEE_OUTPUT_PATH = TABLES_DIR / "finance_by_committee.csv"
SUMMARY_OUTPUT_PATH = TABLES_DIR / "finance_summary.csv"

# Same reading settings as scripts/propose_committee_matches.py.
ISBE_FILE_ENCODING = "cp1252"
RECEIPTS_CHUNK_ROWS = 500_000

# ----- FINANCE_CHOICES (user decisions 2026-11-04; PLAN.md §3) ---------------

# Last day covered by the newest quarterly report in the download. All windows end
# here so every candidate is measured over the same days. UPDATE after each quarterly
# (next: 2026-12-31, reports due mid-January 2027). The script warns if a used report
# ends later than this.
REPORTS_THROUGH_DATE = "2026-09-30"

# Money windows, shown side by side (none is "the" cycle). Each is (first day, last day).
# Starts must be on a quarter start: unitemized gifts exist only as per-report totals.
#   since_2023_07_01  first full quarter after the council was sworn in (May 15, 2023);
#                     closest to the Chicago Reporter convention (since swearing-in)
#   since_2026_01_01  Jan 1 of the year before the election (Block Club 2023 convention)
#   latest_quarter    the newest quarter (Sun-Times convention)
MONEY_WINDOWS = {
    "since_2023_07_01": ("2023-07-01", REPORTS_THROUGH_DATE),
    "since_2026_01_01": ("2026-01-01", REPORTS_THROUGH_DATE),
    "latest_quarter": ("2026-07-01", REPORTS_THROUGH_DATE),
}

# A report counts toward a window only if its whole period is inside the window.
# Reports that cross a window edge are not split; they are counted in the
# <window>_reports_crossing_edge column so you can see what was left out.
WINDOW_REPORT_RULE = "report_period_inside_window"

# FiledDocs document types whose D2Totals are used. Seen for crosswalk committees
# (2026-11-04): Quarterly 3,701, Semiannual 351, Pre-election 95, Final 25, and one
# Statement of Organization carrying D-2 totals (committee 40933, superseded by its
# amended quarterly — see DUPLICATE_PERIOD_RULE).
D2_DOCUMENT_TYPES = {"Quarterly", "Semiannual", "Pre-election", "Final", "Statement of Organization"}

# Superseded reports: D2Totals.Archived = True means replaced by an amendment
# (data dictionary). Those are dropped. If a committee still has 2+ live reports
# ending on the same day, keep the one filed last (FiledDocs.RcvdDateTime). Seen
# 2026-11-04: 3 such cases (39065, 39321, 40933), each an original plus a later
# amendment. Dropped reports stay in finance_reports.csv with used = False.
DUPLICATE_PERIOD_RULE = "keep_latest_filed"

# D2Totals columns added into each figure (data dictionary; I = itemized, NI = not).
RAISED_COLUMNS = ["IndivContribI", "IndivContribNI", "XferInI", "XferInNI", "OtherRctI", "OtherRctNI"]
LOAN_COLUMNS = ["LoanRcvI", "LoanRcvNI"]
IN_KIND_COLUMNS = ["TotalInKind"]
SMALL_DOLLAR_COLUMNS = ["IndivContribNI"]
TRANSFER_IN_COLUMNS = ["XferInI", "XferInNI"]

# Receipts.D2Part codes. The data dictionary says 1-5 (1 individual, 2 transfer in,
# 3 loan, 4 other, 5 in-kind), but the file codes them "1A"-"5A" (counts on
# 2026-11-04, all committees: 1A 4,898,435; 2A 1,122,349; 3A 76,927; 4A 111,579;
# 5A 375,543; plus 34 misaligned rows holding a zip code, "False" or blank).
TRANSFER_IN_PART = "2A"
LOAN_PART = "3A"
IN_KIND_PART = "5A"

# Own-committee transfers are found by name: the receipt's donor name (LastOnlyName +
# FirstName) equals the name of another candidate_sum committee of the same
# candidate, after uppercasing and replacing every non-letter/digit run with one
# space. Receipts carry no donor committee ID, so a name is all there is.
# Every match is printed so it can be checked.
COMMITTEE_NAME_MATCH = "exact_after_uppercase_and_punctuation_to_space"

# A-1 ($1,000+) gifts: ISBE archives an A-1 receipt once a quarterly covers it
# (2026-11-04: 7,762 of 8,206 A-1 rows since 2025 also on a quarterly; all 328
# unarchived rows dated after 2026-09-30, plus 2 from 2009). Counted: unarchived
# A-1 receipts dated after REPORTS_THROUGH_DATE. Own column, not in raised (user
# decision 2026-11-04; may be added to raised later). Unarchived A-1 rows dated
# on or before REPORTS_THROUGH_DATE are printed and not counted.
A1_DOCUMENT_TYPE = "A-1"

# Sunshine-style total (user, 2026-11-12, option 1): a per-committee figure built to line up with
# the "Funds Raised" column of https://illinoissunshine.org/mayoral-races/, so visitors can
# reconcile our numbers with theirs. Sunshine's current code is not public; this rule was found
# by matching their page on 2026-11-12 (session log). It is NOT one of our money windows:
#   sunshine_style_total = D-2 TotalReceipts + TotalInKind on every used report of the types in
#       SUNSHINE_STYLE_DOCUMENT_TYPES (all of the committee's history), PLUS every unarchived A-1
#       receipt dated after REPORTS_THROUGH_DATE (gifts, transfers, loans and in-kind).
#   Includes loans and in-kind; own-committee transfers are not taken out.
# Matched Sunshine to the cent on 2026-11-12 for 6 committees whose first report began in 2025-26
# (Kelly 40942, Quigley 40800, Wilson 41192, Brewer 41238, Quinlan 41442, Nee 41265).
# OPEN QUESTION: for older committees (Giannoulias 19323, Johnson 34198, Mendoza 18308, Cardenas
# 17290) Sunshine starts at some date in spring 2023 that we could not reproduce, so their figure
# here (all history) will be higher than Sunshine's. Holberg 40876: ours is $11,650 higher than
# Sunshine, unexplained. sunshine_style_first_report_begin is written so the start is visible.
# Document types: Quarterly only, as in Sunshine's 2018 code (eads/illinois-sunshine etl.py,
# ContestedRaces_getFundsRaisedTotal); every matched committee had only quarterlies.
SUNSHINE_STYLE_DOCUMENT_TYPES = {"Quarterly"}
SUNSHINE_STYLE_REPORT_COLUMNS = ["TotalReceipts", "TotalInKind"]

# ---------------------------------------------------------------------------

BY_COMMITTEE_KEY = ["candidate_id", "committee_id"]


def read_isbe(file_name, **options):
    """Read one ISBE tab-delimited file as strings (same settings as the other scripts)."""
    return pd.read_csv(ISBE_DIR / file_name, sep="\t", dtype=str, keep_default_na=False,
                       encoding=ISBE_FILE_ENCODING, on_bad_lines="skip", quoting=3, **options)


def committee_name_key(name):
    """Name used for COMMITTEE_NAME_MATCH: uppercase, punctuation runs -> one space."""
    return re.sub(r"[^A-Z0-9]+", " ", name.upper()).strip()


def money(frame, columns):
    """Row sums of D2Totals money columns."""
    return frame[columns].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)


def load_reports(committee_ids):
    """Every D2Totals row of these committees, joined to its FiledDocs row, with used / why."""
    filed_docs = read_isbe("FiledDocs.txt")
    filed_docs = filed_docs[filed_docs["CommitteeID"].isin(committee_ids)]
    documents = filed_docs[["ID", "DocName", "Amend", "RptPdBegDate", "RptPdEndDate", "RcvdDateTime",
                            "Archived"]].rename(columns={"ID": "FiledDocID", "Archived": "document_archived"})
    totals = read_isbe("D2Totals.txt")
    totals = totals[totals["CommitteeID"].isin(committee_ids)]
    reports = totals.merge(documents, on="FiledDocID", how="left")
    reports["period_begin"] = pd.to_datetime(reports["RptPdBegDate"], errors="coerce")
    reports["period_end"] = pd.to_datetime(reports["RptPdEndDate"], errors="coerce")
    reports["filed_at"] = pd.to_datetime(reports["RcvdDateTime"], errors="coerce")

    reports["used"] = True
    reports["not_used_reason"] = ""
    rules = [
        (reports["Archived"] == "True", "superseded_by_amendment"),
        (~reports["DocName"].isin(D2_DOCUMENT_TYPES), "document_type_not_used"),
        (reports["period_end"].isna(), "no_period_dates"),
        (reports["period_end"] > pd.Timestamp(REPORTS_THROUGH_DATE), "after_reports_through_date"),
    ]
    for is_dropped, reason in rules:
        newly_dropped = reports["used"] & is_dropped
        reports.loc[newly_dropped, ["used", "not_used_reason"]] = [False, reason]

    # DUPLICATE_PERIOD_RULE: among live reports for one committee + period end, keep the last filed.
    live = reports[reports["used"]].sort_values("filed_at")
    older_duplicates = live.duplicated(["CommitteeID", "period_end"], keep="last")
    dropped_index = live[older_duplicates].index
    reports.loc[dropped_index, ["used", "not_used_reason"]] = [False, "older_filing_same_period"]
    for row in reports.loc[dropped_index].itertuples():
        print(f"  same period twice: committee {row.CommitteeID}, period ending {row.RptPdEndDate[:10]} — "
              f"dropped FiledDocID {row.FiledDocID} ({row.DocName}, filed {row.RcvdDateTime[:10]})")
    late = reports["Archived"].eq("False") & (reports["period_end"] > pd.Timestamp(REPORTS_THROUGH_DATE))
    if late.any():
        print(f"WARNING: {int(late.sum())} live reports end after REPORTS_THROUGH_DATE {REPORTS_THROUGH_DATE} "
              f"(not used) — update REPORTS_THROUGH_DATE and the windows")
    mismatch = reports["used"] & (reports["document_archived"] == "True")
    if mismatch.any():
        print(f"NOTE: {int(mismatch.sum())} used reports whose FiledDocs row is archived but whose "
              f"D2Totals row is not: {reports.loc[mismatch, 'FiledDocID'].tolist()}")
    return reports, filed_docs


def load_receipts(committee_ids, document_ids):
    """Receipts of these committees on these documents (itemized rows), all D-2 parts."""
    columns = ["CommitteeID", "FiledDocID", "LastOnlyName", "FirstName", "RcvDate", "Amount", "D2Part", "Archived"]
    chunks = []
    for chunk in read_isbe("Receipts.txt", usecols=columns, chunksize=RECEIPTS_CHUNK_ROWS):
        chunks.append(chunk[chunk["CommitteeID"].isin(committee_ids) & chunk["FiledDocID"].isin(document_ids)])
    receipts = pd.concat(chunks, ignore_index=True)
    receipts["amount"] = pd.to_numeric(receipts["Amount"], errors="coerce").fillna(0)
    receipts["received"] = pd.to_datetime(receipts["RcvDate"], errors="coerce")
    receipts["donor_name_key"] = (receipts["LastOnlyName"] + " " + receipts["FirstName"]).map(committee_name_key)
    return receipts


def own_committee_flags(receipts, crosswalk):
    """For each receipt row, True if the donor is another candidate_sum committee of a
    candidate this receiving committee also sums into. Returns a frame keyed by candidate."""
    summed = crosswalk[crosswalk["counts_toward"] == "candidate_sum"]
    summed = summed.assign(name_key=summed["committee_name"].map(committee_name_key))
    rows = []
    for candidate_id, committees in summed.groupby("candidate_id"):
        if len(committees) < 2:
            continue
        for receiving in committees.itertuples():
            other_names = set(committees.loc[committees["committee_id"] != receiving.committee_id, "name_key"])
            matched = receipts[(receipts["CommitteeID"] == receiving.committee_id)
                               & receipts["donor_name_key"].isin(other_names)]
            rows.append(matched.assign(candidate_id=candidate_id))
    if not rows:
        return receipts.iloc[0:0].assign(candidate_id="")
    return pd.concat(rows, ignore_index=True)


def window_figures(reports, own_transfers, window_name, first_day, last_day):
    """Per-committee money for one window (reports wholly inside it)."""
    start, end = pd.Timestamp(first_day), pd.Timestamp(last_day)
    used = reports[reports["used"]]
    inside = used[(used["period_begin"] >= start) & (used["period_end"] <= end)]
    crossing = used[(used["period_begin"] < start) & (used["period_end"] >= start)]
    figures = pd.DataFrame({
        "committee_id": inside["CommitteeID"],
        "raised_before_own_transfers": money(inside, RAISED_COLUMNS),
        "transfers_in": money(inside, TRANSFER_IN_COLUMNS),
        "individual_not_itemized": money(inside, SMALL_DOLLAR_COLUMNS),
        "loans": money(inside, LOAN_COLUMNS),
        "in_kind": money(inside, IN_KIND_COLUMNS),
        "reports": 1,
    }).groupby("committee_id").sum()
    figures[f"reports_crossing_edge"] = crossing.groupby("CommitteeID").size()
    inside_documents = set(inside["FiledDocID"])
    own = own_transfers[own_transfers["FiledDocID"].isin(inside_documents)]
    own_by_key = own.groupby(["candidate_id", "CommitteeID"])["amount"].sum()
    figures = figures.fillna(0)
    return figures.add_prefix(f"{window_name}_"), own_by_key


def main():
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    crosswalk = pd.read_csv(CROSSWALK_PATH, dtype=str, keep_default_na=False)
    rows = crosswalk[crosswalk["counts_toward"] != "excluded"].copy()
    committee_ids = set(rows["committee_id"])
    print(f"crosswalk: {len(rows)} candidate x committee rows used "
          f"({int((crosswalk['counts_toward'] == 'excluded').sum())} excluded rows left out), "
          f"{len(committee_ids)} committees")

    reports, filed_docs = load_reports(committee_ids)
    print(f"D-2 totals rows: {len(reports)}; used: {int(reports['used'].sum())}; "
          f"not used by reason: {reports.loc[~reports['used'], 'not_used_reason'].value_counts().to_dict()}")
    report_columns = ["CommitteeID", "FiledDocID", "DocName", "Amend", "RptPdBegDate", "RptPdEndDate",
                      "RcvdDateTime", "used", "not_used_reason", "Archived", "document_archived"]
    money_columns = [column for column in reports.columns if column[0].isupper()
                     and column not in report_columns and column not in {"ID"}]
    reports.sort_values(["CommitteeID", "period_end", "filed_at"])[report_columns + money_columns].to_csv(
        REPORTS_OUTPUT_PATH, index=False)

    # Itemized receipts: on used D-2 reports (for own-committee transfers) and on A-1s.
    a1_documents = filed_docs[filed_docs["DocName"] == A1_DOCUMENT_TYPE]
    used_documents = set(reports.loc[reports["used"], "FiledDocID"])
    receipts = load_receipts(committee_ids, used_documents | set(a1_documents["ID"]))
    transfer_receipts = receipts[(receipts["D2Part"] == TRANSFER_IN_PART) & (receipts["Archived"] == "False")
                                 & receipts["FiledDocID"].isin(used_documents)]
    own_transfers = own_committee_flags(transfer_receipts, rows)
    print(f"own-committee transfers in (itemized, on used reports): {len(own_transfers)} rows, "
          f"${own_transfers['amount'].sum():,.2f}")
    for row in own_transfers.sort_values(["candidate_id", "received"]).itertuples():
        print(f"  {row.candidate_id}: committee {row.CommitteeID} got ${row.amount:,.2f} on "
              f"{str(row.received)[:10]} from '{row.LastOnlyName} {row.FirstName}'".rstrip())

    # Cash on hand: ending funds on each committee's latest used report.
    latest = reports[reports["used"]].sort_values(["period_end", "filed_at"]).groupby("CommitteeID").tail(1)
    cash = pd.DataFrame({
        "cash_on_hand": pd.to_numeric(latest["EndFundsAvail"], errors="coerce").values,
        "cash_on_hand_report_end": latest["RptPdEndDate"].str[:10].values,
        "cash_on_hand_report_type": latest["DocName"].values,
    }, index=latest["CommitteeID"].values)
    cash["cash_on_hand_is_current"] = cash["cash_on_hand_report_end"] == REPORTS_THROUGH_DATE

    by_committee = rows[["candidate_id", "office_code", "district_number", "ballot_name_raw", "committee_id",
                         "committee_name", "committee_type", "committee_status", "counts_toward",
                         "link_basis"]].copy()
    by_committee = by_committee.join(cash, on="committee_id")

    for window_name, (first_day, last_day) in MONEY_WINDOWS.items():
        figures, own_by_key = window_figures(reports, own_transfers, window_name, first_day, last_day)
        by_committee = by_committee.join(figures, on="committee_id")
        keys = list(zip(by_committee["candidate_id"], by_committee["committee_id"]))
        own_column = f"{window_name}_own_committee_transfers_in"
        by_committee[own_column] = [own_by_key.get(key, 0.0) for key in keys]
        by_committee[f"{window_name}_raised"] = (by_committee[f"{window_name}_raised_before_own_transfers"]
                                                 - by_committee[own_column])

    # A-1 gifts since the last quarterly (unarchived, dated after REPORTS_THROUGH_DATE).
    a1 = receipts[receipts["FiledDocID"].isin(set(a1_documents["ID"])) & (receipts["Archived"] == "False")]
    a1_early = a1[a1["received"] <= pd.Timestamp(REPORTS_THROUGH_DATE)]
    if len(a1_early):
        print(f"NOTE: {len(a1_early)} unarchived A-1 rows dated on/before {REPORTS_THROUGH_DATE} not counted: "
              f"{a1_early[['CommitteeID', 'RcvDate', 'Amount']].values.tolist()}")
    a1 = a1[a1["received"] > pd.Timestamp(REPORTS_THROUGH_DATE)]
    a1_own = own_committee_flags(a1[a1["D2Part"] == TRANSFER_IN_PART], rows)
    a1_own_by_key = a1_own.groupby(["candidate_id", "CommitteeID"])["amount"].sum()
    a1_cash = a1[~a1["D2Part"].isin({LOAN_PART, IN_KIND_PART})].groupby("CommitteeID")["amount"].agg(["sum", "count"])
    a1_loans = a1[a1["D2Part"] == LOAN_PART].groupby("CommitteeID")["amount"].sum()
    a1_in_kind = a1[a1["D2Part"] == IN_KIND_PART].groupby("CommitteeID")["amount"].sum()
    keys = list(zip(by_committee["candidate_id"], by_committee["committee_id"]))
    by_committee["a1_own_committee_transfers_in"] = [a1_own_by_key.get(key, 0.0) for key in keys]
    by_committee["a1_gifts_since_last_report"] = (
        by_committee["committee_id"].map(a1_cash["sum"]).fillna(0) - by_committee["a1_own_committee_transfers_in"])
    by_committee["a1_gift_rows"] = by_committee["committee_id"].map(a1_cash["count"]).fillna(0).astype(int)
    by_committee["a1_loans_since_last_report"] = by_committee["committee_id"].map(a1_loans).fillna(0)
    by_committee["a1_in_kind_since_last_report"] = by_committee["committee_id"].map(a1_in_kind).fillna(0)
    if len(a1):
        print(f"A-1 receipts after {REPORTS_THROUGH_DATE}: {len(a1)} rows, ${a1['amount'].sum():,.2f}, "
              f"latest dated {str(a1['received'].max())[:10]}")

    # Sunshine-style total (see SUNSHINE_STYLE_DOCUMENT_TYPES): all-history D-2 receipts + in-kind,
    # plus every A-1 receipt after REPORTS_THROUGH_DATE.
    sunshine_reports = reports[reports["used"] & reports["DocName"].isin(SUNSHINE_STYLE_DOCUMENT_TYPES)]
    sunshine_d2 = money(sunshine_reports, SUNSHINE_STYLE_REPORT_COLUMNS).groupby(sunshine_reports["CommitteeID"]).sum()
    sunshine_first = sunshine_reports.groupby("CommitteeID")["RptPdBegDate"].min().str[:10]
    a1_all = a1.groupby("CommitteeID")["amount"].sum()
    by_committee["sunshine_style_total"] = (by_committee["committee_id"].map(sunshine_d2).fillna(0)
                                            + by_committee["committee_id"].map(a1_all).fillna(0))
    by_committee["sunshine_style_first_report_begin"] = by_committee["committee_id"].map(sunshine_first)

    by_committee = by_committee.sort_values(BY_COMMITTEE_KEY)
    by_committee.to_csv(BY_COMMITTEE_OUTPUT_PATH, index=False)

    # Per candidate: add up candidate_sum committees only; slates are named.
    summed = by_committee[by_committee["counts_toward"] == "candidate_sum"]
    number_columns = [column for column in summed.columns
                      if column.startswith(tuple(MONEY_WINDOWS)) or column.startswith("a1_")] + ["cash_on_hand"]
    summary = summed.groupby("candidate_id")[number_columns].sum(min_count=1)
    summary["committees_summed"] = summed.groupby("candidate_id")["committee_id"].agg("; ".join)
    summary["committees_with_no_d2_report"] = summed[summed["cash_on_hand_report_end"].isna()].groupby(
        "candidate_id")["committee_id"].agg("; ".join)
    summary["committees_cash_not_current"] = summed[summed["cash_on_hand_is_current"].eq(False)
                                                    & summed["cash_on_hand_report_end"].notna()].groupby(
        "candidate_id")["committee_id"].agg("; ".join)
    slates = by_committee[by_committee["counts_toward"] == "slate_column"]
    summary = summary.join(slates.groupby("candidate_id")["committee_name"].agg("; ".join).rename(
        "slate_committees_not_added"), how="outer")
    candidates = rows.drop_duplicates("candidate_id").set_index("candidate_id")[
        ["office_code", "district_number", "ballot_name_raw"]]
    summary = candidates.join(summary).reset_index()
    window_order = [f"{window}_{suffix}" for window in MONEY_WINDOWS for suffix in
                    ["raised", "individual_not_itemized", "own_committee_transfers_in", "transfers_in",
                     "loans", "in_kind", "reports", "reports_crossing_edge", "raised_before_own_transfers"]]
    a1_order = ["a1_gifts_since_last_report", "a1_gift_rows", "a1_loans_since_last_report",
                "a1_in_kind_since_last_report", "a1_own_committee_transfers_in"]
    summary = summary[["candidate_id", "office_code", "district_number", "ballot_name_raw", "cash_on_hand",
                       *window_order, *a1_order, "committees_summed", "committees_with_no_d2_report",
                       "committees_cash_not_current", "slate_committees_not_added"]]
    summary.to_csv(SUMMARY_OUTPUT_PATH, index=False)

    print(f"candidates in summary: {len(summary)}; with a cash-on-hand figure: "
          f"{int(summary['cash_on_hand'].notna().sum())}")
    print(f"settings: REPORTS_THROUGH_DATE={REPORTS_THROUGH_DATE}, WINDOW_REPORT_RULE={WINDOW_REPORT_RULE}, "
          f"DUPLICATE_PERIOD_RULE={DUPLICATE_PERIOD_RULE}, COMMITTEE_NAME_MATCH={COMMITTEE_NAME_MATCH}")
    for path in [REPORTS_OUTPUT_PATH, BY_COMMITTEE_OUTPUT_PATH, SUMMARY_OUTPUT_PATH]:
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
