"""Local ward-by-ward money dashboard: one self-contained HTML file, opened from disk.

No server and no internet needed: the data is embedded in the page as JSON, and the page uses
plain JavaScript (no libraries). Open dashboard/index.html in a browser.

Only reshapes; every number shown is a cell of data/tables/display_candidates.csv or
display_committees.csv (scripts/build_display_tables.py), except the three per-race figures
in RACE_STATS, which are computed here and printed so they can be checked.

Inputs:
  data/tables/display_candidates.csv
  data/tables/display_committees.csv
  scripts/dashboard_template.html        page layout, styles and drawing code
Output:
  dashboard/index.html

Usage:
  python scripts/build_dashboard.py
"""

import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLES_DIR = REPO_ROOT / "data" / "tables"
CANDIDATES_PATH = TABLES_DIR / "display_candidates.csv"
COMMITTEES_PATH = TABLES_DIR / "display_committees.csv"
TEMPLATE_PATH = REPO_ROOT / "scripts" / "dashboard_template.html"
OUTPUT_PATH = REPO_ROOT / "dashboard" / "index.html"

# Placeholder in the template that the data JSON replaces.
DATA_PLACEHOLDER = "/*DASHBOARD_DATA*/null"

# Dates printed on the page. REPORTS_THROUGH_LABEL: UPDATE with each new quarterly
# (REPORTS_THROUGH_DATE in build_finance_tables.py).
REPORTS_THROUGH_LABEL = "Sep 30, 2026"

# Ways for visitors to report errors or send updates (user, 2026-11-12). An empty string hides
# that link on the page.
#   FEEDBACK_FORM_URL          Google Form, general link (page footer). OPEN: the user creates the form.
#   FEEDBACK_FORM_PREFILL_URL  the form's "Get pre-filled link" URL with the candidate answers
#                              replaced by {candidate_id} and {candidate_name}; each candidate row
#                              then gets a "Report a problem" link with those filled in.
#   GITHUB_ISSUES_URL          for code bugs, once the repo is public (it is private on 2026-11-12):
#                              https://github.com/lukeleisman/election_candidate_info/issues
#   CONTACT_EMAIL              general questions, comments, updates (page footer).
# Form "Corrections and Updates to Chicago Elections Dashboard" (user, 2026-11-12). Pre-fill IDs
# read from the public form page 2026-11-12: entry.975812737 = "Candidate ID",
# entry.2031813816 = "Candidate name". If the form's questions are rebuilt, these IDs change.
FEEDBACK_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd3QGQVBxoQNP20o6yWiZtQ87yh5JHZWzD92jF7Q4YxAWOtyw/viewform"
FEEDBACK_FORM_PREFILL_URL = ("https://docs.google.com/forms/d/e/1FAIpQLSd3QGQVBxoQNP20o6yWiZtQ87yh5JHZWzD92jF7Q4YxAWOtyw/viewform?usp=pp_url"
                             "&entry.975812737={candidate_id}&entry.2031813816={candidate_name}")
GITHUB_ISSUES_URL = ""
CONTACT_EMAIL = "hello@lukeleisman.com"

# Download date (changed 2026-11-12 from a hand-typed label): the newest retrieved_at of
# this file in data/raw/isbe/manifest.json (scripts/fetch_isbe.py). Receipts.txt is the
# file the money figures come from; the other ISBE files may have other dates.
ISBE_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "isbe" / "manifest.json"
ISBE_DOWNLOAD_DATE_FILE = "Receipts.txt"


def isbe_download_label():
    """'Nov 12, 2026': newest manifest download of ISBE_DOWNLOAD_DATE_FILE (UTC date)."""
    from datetime import datetime
    downloads = [row["retrieved_at"] for row in json.loads(ISBE_MANIFEST_PATH.read_text())
                 if row["file"] == ISBE_DOWNLOAD_DATE_FILE]
    newest = datetime.strptime(max(downloads)[:10], "%Y-%m-%d")
    return f"{newest:%b} {newest.day}, {newest.year}"

# Race shown when the page opens.
DEFAULT_RACE_KEY = "ALD-01"

# Money windows (build_finance_tables.MONEY_WINDOWS), in picker order; first is the default.
WINDOWS = [
    ("since_2026_01_01", "Since Jan 1, 2026"),
    ("latest_quarter", "Jul 1 – Sep 30, 2026 (latest quarter)"),
    ("since_2023_07_01", "Since Jul 1, 2023"),
]

# Candidate table columns: (CSV column, "{window}" filled from the picker; short header shown in
# the table; full description shown as the header's tooltip; format). Headers shortened and
# allowed to wrap 2026-11-12 (user: table too wide).
CANDIDATE_COLUMNS = [
    ("cash_on_hand", "Cash", "Cash on hand at the latest report", "money"),
    ("{window}_raised", "Raised", "Raised in the money window (all incoming cash; no loans or in-kind)", "money"),
    ("a1_gifts_since_last_report", "$1K+ gifts after Sep 30", "$1,000+ gifts reported on A-1s after the Sep 30 quarterly", "money"),
    ("{window}_loans", "Loans", "Loans received in the money window", "money"),
    ("{window}_in_kind", "In-kind", "In-kind gifts in the money window", "money"),
    ("{window}_unique_donors", "Donors", "Unique itemized donors (last name + first name + zip)", "count"),
    ("{window}_not_itemized_individual_pct", "Small gifts", "Gifts too small to itemize, as a share of all receipts", "pct"),
    ("{window}_top10_share_of_raised", "Top 10 share", "Share of raised from the 10 largest donors", "pct"),
    ("{window}_median_gift", "Median gift", "Median itemized gift from people", "money"),
    ("{window}_chicago_by_zip_share", "Chicago zips", "Share of itemized dollars from 606xx zip codes", "pct"),
]

# Per-race figures over candidates in the race, second filings by one person left out
# (duplicate_filing_of non-blank). "with_committee" = committees_added > 0.
RACE_STATS = ["candidates", "with_committee", "cash_on_hand_total"]

# ---------------------------------------------------------------------------


def records(frame):
    """Rows as dicts with blanks as None (JSON null)."""
    return frame.astype(object).where(frame.notna(), None).replace({"": None}).to_dict(orient="records")


def main():
    candidates = pd.read_csv(CANDIDATES_PATH, dtype=str, keep_default_na=False)
    committees = pd.read_csv(COMMITTEES_PATH, dtype=str, keep_default_na=False)

    people = candidates[candidates["duplicate_filing_of"] == ""]
    race_stats = people.groupby("race_key").agg(
        candidates=("candidate_id", "size"),
        with_committee=("committees_added", lambda values: int((values.astype(int) > 0).sum())),
        cash_on_hand_total=("cash_on_hand", lambda values: pd.to_numeric(values, errors="coerce").fillna(0).sum()),
    ).reset_index()
    races = candidates.drop_duplicates("race_key")[["race_key", "race_label", "race_order"]]
    races = races.assign(race_order=races["race_order"].astype(int)).sort_values("race_order")
    races = races.merge(race_stats, on="race_key", how="left")

    data = {
        "reports_through": REPORTS_THROUGH_LABEL,
        "isbe_download": isbe_download_label(),
        "feedback": {"form_url": FEEDBACK_FORM_URL, "form_prefill_url": FEEDBACK_FORM_PREFILL_URL,
                     "github_issues_url": GITHUB_ISSUES_URL, "contact_email": CONTACT_EMAIL},
        "default_race": DEFAULT_RACE_KEY,
        "windows": [{"key": key, "label": label} for key, label in WINDOWS],
        "candidate_columns": [{"column": column, "header": header, "description": description, "format": fmt}
                              for column, header, description, fmt in CANDIDATE_COLUMNS],
        "races": records(races),
        "candidates": records(candidates),
        "committees": records(committees),
    }
    template = TEMPLATE_PATH.read_text()
    if DATA_PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE_PATH.name} has no {DATA_PLACEHOLDER} placeholder")
    page = template.replace(DATA_PLACEHOLDER, json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page)

    print(f"{len(races)} races, {len(candidates)} candidate rows, {len(committees)} committee rows")
    print("per-race figures (check against display_candidates.csv):")
    print(races[["race_label", *RACE_STATS]].to_string(index=False))
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} — open it in a browser")


if __name__ == "__main__":
    main()
