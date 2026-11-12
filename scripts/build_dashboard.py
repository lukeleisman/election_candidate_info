"""Local ward-by-ward money dashboard: one self-contained HTML file, opened from disk.

No server and no internet needed: the data is embedded in the page as JSON, and the page uses
plain JavaScript (no libraries). Open dashboard/index.html in a browser.

Only reshapes; every number shown is a cell of data/tables/display_candidates.csv or
display_committees.csv (scripts/build_display_tables.py), except the three per-race figures
in RACE_STATS, which are computed here and printed so they can be checked.

Inputs:
  data/tables/display_candidates.csv
  data/tables/display_committees.csv
  data/tables/incumbents.csv          scripts/check_incumbents.py   (i) marker
  data/tables/candidate_links.csv     scripts/build_candidate_links.py
  data/tables/top_donors.csv          scripts/build_donor_mix.py
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
INCUMBENTS_PATH = TABLES_DIR / "incumbents.csv"
LINKS_PATH = TABLES_DIR / "candidate_links.csv"
TOP_DONORS_PATH = TABLES_DIR / "top_donors.csv"
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

# Links to each committee's own pages, so visitors can explore beyond the dashboard (user,
# 2026-11-12). (label shown, URL with {committee_id} = ISBE committee ID, tooltip). Shown in the
# committee table and under each candidate's committees. Both formats checked 2026-11-12 with
# committee 34616 (La Spata): each returned 200 and the committee's page. An empty list hides them.
COMMITTEE_SOURCE_LINKS = [
    ("ISBE", "https://www.elections.il.gov/CampaignDisclosure/CommitteeDetail.aspx?id={committee_id}",
     "Official filings at the Illinois State Board of Elections"),
    ("Sunshine", "https://illinoissunshine.org/committees/{committee_id}/",
     "Illinois Sunshine (Reform for Illinois): the same state data, with donor and spending detail"),
]

# Page-level sources listed in the "Sources" section: (name, URL, what we take from it).
DATA_SOURCES = [
    ("Chicago Board of Election Commissioners: candidates", "https://chicagoelections.gov/getting-ballot/candidates",
     "who filed to be on the ballot (scripts/fetch_cboe.py)"),
    ("Illinois State Board of Elections: campaign disclosure data files",
     "https://www.elections.il.gov/CampaignDisclosureDataFiles/",
     "committees, reports and receipts behind every money figure (scripts/fetch_isbe.py)"),
    ("Illinois Sunshine", "https://illinoissunshine.org/",
     "not used for the numbers; the same state data in a friendlier site, linked per committee"),
]

# Sunshine-style total column in the committee table (user, 2026-11-12, option 1;
# sunshine_style_total in build_finance_tables.py). Shown only for committees whose first quarterly
# began on or after this date; older committees show "not comparable", because our figure covers
# all their history while Sunshine starts somewhere in spring 2023 (OPEN QUESTION there).
# 2023-07-01 = the same start as our longest money window; every committee that matched Sunshine
# exactly on 2026-11-12 began in 2025-26. Empty string hides the column.
SUNSHINE_STYLE_SHOWN_IF_FIRST_REPORT_ON_OR_AFTER = "2023-07-01"

# Labels for link kinds in the candidate sections (kinds: build_candidate_links.LINK_KIND_ORDER).
LINK_KIND_LABELS = {"campaign": "Campaign site", "office": "Office site", "social": "Social",
                    "fundraising": "Fundraising page", "endorsements": "Endorsements page", "other": "Other"}

# Incumbent marker text and the date the incumbent table describes (data/input/incumbents_manual.csv).
# FUTURE ELECTIONS: the incumbents table is for the Feb 2027 election only (scripts/check_incumbents.py).
INCUMBENT_AS_OF_LABEL = "Nov 2026"

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

    incumbents = pd.read_csv(INCUMBENTS_PATH, dtype=str, keep_default_na=False)
    links = pd.read_csv(LINKS_PATH, dtype=str, keep_default_na=False)
    top_donors = pd.read_csv(TOP_DONORS_PATH, dtype=str, keep_default_na=False)
    shown_ids = set(candidates["candidate_id"])
    for name, frame in [("incumbents", incumbents), ("links", links), ("top donors", top_donors)]:
        unknown = sorted(set(frame["candidate_id"]) - shown_ids)
        if unknown:
            print(f"NOTE: {name} rows for candidates not on the page (left out): {unknown}")

    # Raised vs the sum of its D-2 lines (mix_raised, from donor_mix.csv): printed if they differ.
    for window_key, _ in WINDOWS:
        difference = (pd.to_numeric(candidates[f"{window_key}_raised"], errors="coerce")
                      - pd.to_numeric(candidates[f"{window_key}_mix_raised"], errors="coerce")).abs()
        if (difference > 0.01).any():
            print(f"NOTE {window_key}: raised differs from its breakdown for "
                  f"{candidates.loc[difference > 0.01, 'candidate_id'].tolist()}")

    data = {
        "reports_through": REPORTS_THROUGH_LABEL,
        "isbe_download": isbe_download_label(),
        "feedback": {"form_url": FEEDBACK_FORM_URL, "form_prefill_url": FEEDBACK_FORM_PREFILL_URL,
                     "github_issues_url": GITHUB_ISSUES_URL, "contact_email": CONTACT_EMAIL},
        "committee_source_links": [{"label": label, "url": url, "description": description}
                                   for label, url, description in COMMITTEE_SOURCE_LINKS],
        "data_sources": [{"name": name, "url": url, "use": use} for name, url, use in DATA_SOURCES],
        "sunshine_style_cutoff": SUNSHINE_STYLE_SHOWN_IF_FIRST_REPORT_ON_OR_AFTER,
        "default_race": DEFAULT_RACE_KEY,
        "windows": [{"key": key, "label": label} for key, label in WINDOWS],
        "candidate_columns": [{"column": column, "header": header, "description": description, "format": fmt}
                              for column, header, description, fmt in CANDIDATE_COLUMNS],
        "incumbent_as_of": INCUMBENT_AS_OF_LABEL,
        "link_kind_labels": LINK_KIND_LABELS,
        "incumbents": records(incumbents[["candidate_id", "officeholder_name", "source_url"]]),
        "links": records(links[["candidate_id", "link_kind", "platform", "url", "found_by", "source_statuses"]]),
        "top_donors": records(top_donors),
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
