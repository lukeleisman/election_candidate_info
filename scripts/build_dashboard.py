"""Local ward-by-ward candidate dashboard (money, links, social media): one self-contained HTML file.

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
  data/endorsements/social_accounts_google.csv     scripts/extract_social_from_google.py
  data/endorsements/candidate_campaign_sites_google.csv   which candidates the Google pass has searched
  data/endorsements/endorsements.csv               scripts/match_endorsements.py
  scripts/dashboard_template.html        page layout, styles and drawing code
Output:
  dashboard/index.html               local page, data embedded
  docs/dashboard/app.js, docs/data/dashboard.json, docs/index.html   embedded build for the website
                                     (EMBED_* settings below)

Usage:
  python scripts/build_dashboard.py
"""

import json
import re
from pathlib import Path

import pandas as pd

# Platform order mirrors the parser's list (scripts/extract_social_from_google.py).
from extract_social_from_google import PLATFORMS as SOCIAL_PLATFORM_ORDER

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
SOCIAL_ACCOUNTS_PATH = REPO_ROOT / "data" / "endorsements" / "social_accounts_google.csv"
GOOGLE_PASS_PATHS = [REPO_ROOT / "data" / "endorsements" / "candidate_campaign_sites_google.csv",
                     REPO_ROOT / "data" / "endorsements" / "candidate_campaign_sites_google_social_rerun.csv"]
# Hand-edited (user, 2026-11-13): flags on single accounts, shown next to the account on the page
# (e.g. "May not be this candidate"; later "Verified"). Key: candidate_id + platform + handle (any case).
SOCIAL_FLAGS_PATH = REPO_ROOT / "data" / "endorsements" / "social_account_flags.csv"
# Hand-edited review of post authors (extract_social_from_google.POST_AUTHORS_REVIEW_FILE).
POST_AUTHORS_REVIEW_PATH = REPO_ROOT / "data" / "endorsements" / "social_post_authors_review.csv"
# Endorsement rows with their proposed candidate match (scripts/match_endorsements.py).
ENDORSEMENTS_PATH = REPO_ROOT / "data" / "endorsements" / "endorsements.csv"
# Which endorsement rows the page shows, by review_status. PLAN.md §4 says reviewed rows only.
# Set 2026-11-14 to also show unreviewed rows, each tagged "Not checked yet". User 2026-11-14: keep showing
# them after publishing too (see EMBED_ENDORSEMENT_PAGE_REVIEW_STATUSES for the website build).
ENDORSEMENT_PAGE_REVIEW_STATUSES = ["reviewed", "unreviewed"]
# Which match statuses are shown. judgment_call rows are tagged "Name match not confirmed".
ENDORSEMENT_PAGE_MATCH_STATUSES = ["accepted", "judgment_call"]
# Endorser type labels on the page (keys = match_endorsements.ENDORSER_TYPES).
ENDORSER_TYPE_LABELS = {"union": "Union", "advocacy_org": "Advocacy group", "political_org": "Political group",
                        "party_or_ward_org": "Party / ward org", "elected_official": "Elected official",
                        "former_official": "Former official", "newspaper": "Newspaper",
                        "business_org": "Business group", "person": "Person"}
ENDORSEMENT_PAGE_COLUMNS = ["candidate_id_proposed", "endorser_name", "endorser_type", "endorsement_kind", "cycle", "url",
                            "announced_on", "seen_on", "review_status", "match_status"]
TEMPLATE_PATH = REPO_ROOT / "scripts" / "dashboard_template.html"
OUTPUT_PATH = REPO_ROOT / "dashboard" / "index.html"

# Placeholder in the template that the data JSON replaces.
DATA_PLACEHOLDER = "/*DASHBOARD_DATA*/null"

# ---- Embedded build for lukeleisman.com (added 2026-11-14) ----
# Same pattern as chicago_council/docs/dashboard/app.js: GitHub Pages serves docs/ from main, and the website
# page is an empty <div id="candidates-app"></div> plus <script src=".../dashboard/app.js">. app.js injects the
# template's CSS (already scoped to #candidates-app), puts the template's markup in the div, fetches the data
# JSON from ../data/ next to its own URL, then runs the template's script. All three pieces are cut from
# dashboard_template.html between the APP_*_BEGIN / APP_*_END markers, so the local page and the website
# page are always the same code.
#   WRITE_EMBED_BUILD   False skips docs/ (local page only).
#   EMBED_DIR           served by GitHub Pages (repo setting: branch main, folder /docs).
#   EMBED_CONTAINER_ID  must match the div on the website page and the CSS scope in the template.
#   EMBED_DATA_FILE     one JSON file = the same DATA object the local page embeds (~1.3 MB, most of it top
#                       donors; Pages serves it gzipped). Split per race later if load time is a problem.
#   EMBED_TEST_PAGE     docs/index.html, a bare page that loads app.js the way the website will (local check:
#                       `cd docs && python3 -m http.server 8766`; not 8765, which is the user's own server).
WRITE_EMBED_BUILD = True
EMBED_DIR = REPO_ROOT / "docs"
EMBED_APP_PATH = EMBED_DIR / "dashboard" / "app.js"
EMBED_DATA_FILE = "dashboard.json"
EMBED_DATA_PATH = EMBED_DIR / "data" / EMBED_DATA_FILE
EMBED_TEST_PAGE_PATH = EMBED_DIR / "index.html"
EMBED_CONTAINER_ID = "candidates-app"
# Endorsement rows shown on the PUBLISHED (embedded) page, by review_status. User, 2026-11-14 (later the same
# day, replacing "reviewed only once published"): show all endorsements on the website too, with unreviewed rows
# tagged "Not checked yet" (the tag comes from endorsementTags() in the template). ["reviewed"] = reviewed only.
EMBED_ENDORSEMENT_PAGE_REVIEW_STATUSES = ["reviewed", "unreviewed"]
# Template markers that bound each piece copied into app.js (each must appear exactly once).
APP_CSS_MARKERS = ("/* APP_CSS_BEGIN", "/* APP_CSS_END */")
APP_MARKUP_MARKERS = ("<!-- APP_MARKUP_BEGIN", "<!-- APP_MARKUP_END -->")
APP_SCRIPT_MARKERS = ("// APP_SCRIPT_BEGIN", "// APP_SCRIPT_END")
# Dark mode on the website (user, 2026-11-14: light only, because lukeleisman.com has no dark mode, so a dark
# dashboard would be a dark block in a light page). False = the dark-colors block (between the APP_DARK markers
# in the template) is left out of app.js. The local page still follows the system setting.
EMBED_DARK_MODE = False
APP_DARK_MARKERS = ("/* APP_DARK_BEGIN", "/* APP_DARK_END */")

# Page title and the sentence under it (user, 2026-11-13: general, not money-only). Placed into the
# template's __PAGE_TITLE__ / __PAGE_DESCRIPTION__. Money-specific dates moved to the money section.
PAGE_TITLE = "Chicago 2027 Candidate Information"
# Description wording: the user's own text (2026-11-13).
PAGE_DESCRIPTION = ("This page exists to assist in evaluating races in Chicago's February 23, 2027 municipal "
                    "election (mayor, clerk, treasurer and the 50 aldermanic races). It collects information "
                    "like funds raised, endorsements, social media following and web presence for filed "
                    "candidates in each race.")
# ---- Dates on the page: none typed here (user, 2026-11-15: they must update by themselves) ----
# Quarterly date: REPORTS_THROUGH_DATE in build_finance_tables.py, the one setting to change after each quarterly.
# Every label below (warning, window names, column headers, notes) is built from it.
from datetime import date as _date
from build_finance_tables import MONEY_WINDOWS, REPORTS_THROUGH_DATE, WINDOWS_PLUS_A1_GIFTS


def date_label(iso_day, with_year=True):
    """'2026-09-30' -> 'Sep 30, 2026' (or 'Sep 30')."""
    day = _date.fromisoformat(iso_day[:10])
    return f"{day:%b} {day.day}" + (f", {day.year}" if with_year else "")


REPORTS_THROUGH_LABEL = date_label(REPORTS_THROUGH_DATE)               # "Sep 30, 2026"
REPORTS_THROUGH_SHORT = date_label(REPORTS_THROUGH_DATE, with_year=False)  # "Sep 30" (column headers)

# Warning under the description (user, 2026-11-14; user's draft, reworded for accuracy). The user's draft said
# gifts under $1,000 are reported once a quarter. Illinois rule (10 ILCS 5/9-10): gifts of $1,000+ go on an A-1
# within 5 business days (2 business days in the last 30 days before an election); smaller gifts and all
# spending appear only on the quarterly D-2. Cash on hand stops at the last quarterly (REPORTS_THROUGH_LABEL).
# Last sentence changed 2026-11-15 (Raised now adds later $1,000+ gifts for the "since" periods; user decision A); wording approved by the user 2026-11-15).
PAGE_WARNING = ("IMPORTANT: the data on this page is NOT complete and likely contains errors. Gifts of $1,000 or "
                "more are reported within days, but smaller gifts and all spending are reported only once a "
                f"quarter. The latest quarterly reports run through {REPORTS_THROUGH_LABEL}, so Cash on hand is as "
                "of that date, and after it Raised counts only the $1,000+ gifts.")
TEMPLATE_TEXT_PLACEHOLDERS = {"__PAGE_TITLE__": PAGE_TITLE, "__PAGE_DESCRIPTION__": PAGE_DESCRIPTION,
                              "__PAGE_WARNING__": PAGE_WARNING}

# Ways for visitors to report errors or send updates (user, 2026-11-12). An empty string hides
# that link on the page.
#   FEEDBACK_FORM_URL          Google Form, general link (page footer). OPEN: the user creates the form.
#   FEEDBACK_FORM_PREFILL_URL  the form's "Get pre-filled link" URL with the candidate answers
#                              replaced by {candidate_id} and {candidate_name}; each candidate row
#                              then gets a "Report a problem" link with those filled in.
#   GITHUB_ISSUES_URL          for code bugs (repo public since 2026-11-14):
#                              https://github.com/lukeleisman/election_candidate_info/issues
#   CONTACT_EMAIL              general questions, comments, updates (page footer).
# Form "Corrections and Updates to Chicago Elections Dashboard" (user, 2026-11-12). Pre-fill IDs
# read from the public form page 2026-11-12: entry.975812737 = "Candidate ID",
# entry.2031813816 = "Candidate name". If the form's questions are rebuilt, these IDs change.
FEEDBACK_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSd3QGQVBxoQNP20o6yWiZtQ87yh5JHZWzD92jF7Q4YxAWOtyw/viewform"
FEEDBACK_FORM_PREFILL_URL = ("https://docs.google.com/forms/d/e/1FAIpQLSd3QGQVBxoQNP20o6yWiZtQ87yh5JHZWzD92jF7Q4YxAWOtyw/viewform?usp=pp_url"
                             "&entry.975812737={candidate_id}&entry.2031813816={candidate_name}")
# Set 2026-11-14 when the repo went public (user OK).
GITHUB_ISSUES_URL = "https://github.com/lukeleisman/election_candidate_info/issues"
CONTACT_EMAIL = "hello@lukeleisman.com"

# Download date (changed 2026-11-12 from a hand-typed label): the newest retrieved_at of
# this file in data/raw/isbe/manifest.json (scripts/fetch_isbe.py). Receipts.txt is the
# file the money figures come from; the other ISBE files may have other dates.
ISBE_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "isbe" / "manifest.json"
ISBE_DOWNLOAD_DATE_FILE = "Receipts.txt"


# Candidate list date (user, 2026-11-15: show when it was last checked, and keep it current). Read from the data:
# the Board of Elections PDF named in candidates_cboe.csv (source_pdf) and that PDF's download time in the
# fetch manifest (scripts/fetch_cboe.py). Re-fetching the list (make candidates) updates it.
CBOE_CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
CBOE_MANIFEST_PATH = REPO_ROOT / "data" / "raw" / "cboe" / "manifest.json"
# Text after the date in the Summary note. NOT a date, but it goes stale: UPDATE when the Electoral Board has
# ruled on the petition objections (or when ballot_status.csv is on the page).
CANDIDATE_LIST_STATUS_NOTE = ("Objections to nominating petitions are still being decided, so some candidates may "
                              "not make the ballot.")


def candidate_list_checked_label():
    """'Oct 27, 2026': when the PDF the candidate table was parsed from was downloaded."""
    source_pdfs = set(pd.read_csv(CBOE_CANDIDATES_PATH, dtype=str, keep_default_na=False)["source_pdf"])
    if len(source_pdfs) != 1:
        raise SystemExit(f"candidates_cboe.csv names {len(source_pdfs)} source PDFs (expected 1): {source_pdfs}")
    pdf_name = source_pdfs.pop()
    downloads = [row["retrieved_at"] for row in json.loads(CBOE_MANIFEST_PATH.read_text())
                 if row.get("local_path", "").endswith("/" + pdf_name)]
    if not downloads:
        raise SystemExit(f"{pdf_name} is not in {CBOE_MANIFEST_PATH}")
    return date_label(max(downloads))


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

# Social media follower estimates (user, 2026-11-13: race table + a block per candidate).
# Source: data/endorsements/social_accounts_google.csv, Google's rounded counts ("2.2K+") as shown in
# saved search results. Accounts are NOT matched to the candidate by hand: an account listed in the
# results may be a campaign, office or personal account, or a same-named person. The page says so.
#   SOCIAL_COLLAPSE_EXACT_REPEATS  True: an account listed twice for one candidate with the SAME count
#       (twice on one results page, or in both searches) is shown once. Same name but a different
#       count is kept as two rows (e.g. ALD-16-003 LinkedIn "Cheryl Blackmond" 180+ and 5).
#   SOCIAL_LINK_IF_HANDLE_IN_URL   True: a handle-like label (no spaces) is linked when it appears
#       (any case) in the URL of one of the candidate's social links in candidate_links.csv.
#       Google's labels for Facebook/LinkedIn are display names, so those are rarely linked.
#   SOCIAL_PROFILE_URL_TEMPLATES   (user, 2026-11-13: link every account) when no recorded URL matched,
#       build the profile URL from the handle: {platform: (columns to take the handle from, tried in
#       order; URL pattern; pattern the handle must fully match)}. "account_label" = Google's account
#       label (a handle on Instagram/X; a display name on Facebook/TikTok, which then fails the pattern);
#       "title_handle" = "(@handle)" in the result title (extract_social_from_google.py).
#   SOCIAL_TITLE_HANDLE_ONLY_IF_TITLE_STARTS_WITH_LABEL  True: use title_handle only when the title line
#       begins with the account label, i.e. the title is this account's own (guards against a title
#       from a neighboring result).
#       Built URLs are NOT loaded or checked; the page says "built from the handle" on hover.
#       LinkedIn: no handle in Google's results, so not linked. YouTube: label is a channel name; not linked.
#   SOCIAL_TABLE_ORDER             "ballot": race table rows in candidate ID order (same as the
#       candidate sections). Alternative "largest": by the largest single account, descending.
SOCIAL_COLLAPSE_EXACT_REPEATS = True
SOCIAL_LINK_IF_HANDLE_IN_URL = True
SOCIAL_PROFILE_URL_TEMPLATES = {
    "Instagram": (["account_label", "title_handle"], "https://www.instagram.com/{handle}/", r"[A-Za-z0-9._]+"),
    "X": (["account_label", "title_handle"], "https://x.com/{handle}", r"[A-Za-z0-9_]+"),
    "TikTok": (["account_label", "title_handle"], "https://www.tiktok.com/@{handle}", r"[A-Za-z0-9._]+"),
    "Threads": (["account_label", "title_handle"], "https://www.threads.net/@{handle}", r"[A-Za-z0-9._]+"),
    "Facebook": (["title_handle"], "https://www.facebook.com/{handle}", r"[A-Za-z0-9.]+"),
}
SOCIAL_TITLE_HANDLE_ONLY_IF_TITLE_STARTS_WITH_LABEL = True
# Post authors (seen only as "account › posts" in the candidate's results) are shown only when the user's
# verdict in social_post_authors_review.csv equals this value; blank / other verdicts are left off.
POST_AUTHOR_VERDICT_SHOWN = "candidate"
SOCIAL_TABLE_ORDER = "largest"  # user, 2026-11-13: order by following

# Money chart (user, 2026-11-13: Raised and Cash on the same plot, ordered by Raised). One shared
# dollar scale per race, two bars per candidate.
#   MONEY_CHART_ORDER  "raised": by Raised in the picked window, largest first (no report last).
#                      Alternative "cash": by cash on hand.
MONEY_CHART_ORDER = "raised"

# Race shown when the page opens.
DEFAULT_RACE_KEY = "ALD-01"

# Money windows (build_finance_tables.MONEY_WINDOWS), in picker order; first is the default. Labels are built from
# the window dates (changed 2026-11-15 from typed labels): "Since Jan 1, 2026"; the latest quarter as
# "Jul 1 – Sep 30, 2026 (latest quarter)".
WINDOW_PICKER_ORDER = ["since_2026_01_01", "latest_quarter", "since_2023_07_01"]


def window_label(key):
    first_day, last_day = MONEY_WINDOWS[key]
    if key == "latest_quarter":
        return f"{date_label(first_day, with_year=False)} – {date_label(last_day)} (latest quarter)"
    return f"Since {date_label(first_day)}"


WINDOWS = [(key, window_label(key)) for key in WINDOW_PICKER_ORDER]
# Second filings by the same person (data/candidates/duplicate_filings.csv; Scott ward 24, Nugent ward 39).
# User, 2026-11-15: hide them everywhere. False = left out of the page data entirely.
SHOW_SECOND_FILINGS = False

# Candidate table columns: (CSV column, "{window}" filled from the picker; short header shown in
# the table; full description shown as the header's tooltip; format). Headers shortened and
# allowed to wrap 2026-11-12 (user: table too wide).
# User, 2026-11-15: this table splits Raised into "Raised through <last quarterly>" and "$1K+ after <it>"; the
# Summary and the chart add the two for the "since" periods (WINDOWS_PLUS_A1_GIFTS).
# Chicago column (user, 2026-11-15): "From Chicago", City says Chicago OR zip starts 606 (was zip only).
CANDIDATE_COLUMNS = [
    ("cash_on_hand", "Cash", f"Cash on hand at the latest quarterly report ({REPORTS_THROUGH_LABEL})", "money"),
    ("{window}_raised", f"Raised through {REPORTS_THROUGH_SHORT}",
     f"Raised in the period, on reports through {REPORTS_THROUGH_LABEL} (no loans or in-kind)", "money"),
    ("a1_gifts_since_last_report", f"$1K+ after {REPORTS_THROUGH_SHORT}",
     f"$1,000+ gifts reported on A-1s after the {REPORTS_THROUGH_LABEL} quarterly", "money"),
    ("{window}_loans", "Loans", "Loans received in the money window", "money"),
    ("{window}_in_kind", "In-kind", "In-kind gifts in the money window", "money"),
    ("{window}_unique_donors", "Donors", "Unique itemized donors (last name + first name + zip)", "count"),
    ("{window}_not_itemized_individual_pct", "Small gifts", "Gifts too small to itemize, as a share of all receipts", "pct"),
    ("{window}_top10_share_of_raised", "Top 10 share", "Share of raised from the 10 largest donors", "pct"),
    ("{window}_median_gift", "Median gift", "Median itemized gift from people", "money"),
    ("{window}_chicago_share", "From Chicago", "Share of itemized dollars from donors with a Chicago address or 606xx zip", "pct"),
]

# Summary table at the top of the page (user, 2026-11-14; replaces the three stat boxes). One row per
# candidate (second filings left out, as in the other race tables), then a race total row.
#   Website: SUMMARY_WEBSITE_LINK_KINDS tried in order; the first link of the first kind found is shown
#       (candidate_links.csv order: source user > google > google_social_rerun > first pass). "office" is
#       labeled as an office site. (user: campaign, else office)
#   Cash / Raised: cash_on_hand and the window's Raised field from display_candidates.csv: <window>_raised_plus_a1_gifts
#       for WINDOWS_PLUS_A1_GIFTS, else <window>_raised (user, 2026-11-15). The money chart uses the same field.
#   Largest following: the single account with the largest Google follower floor (user: "just do the largest
#       single account"; not a sum). Accounts with a hand flag (social_account_flags.csv) are skipped when
#       SUMMARY_SKIP_FLAGGED_ACCOUNTS is True; accounts with no count are never picked.
#   Endorsements: number of rows with endorsement_kind "endorsement" shown on the page; the same count as the
#       Endorsements table (so it includes rows not checked yet and name matches not confirmed, per
#       ENDORSEMENT_PAGE_REVIEW_STATUSES / ENDORSEMENT_PAGE_MATCH_STATUSES).
#   SUMMARY_TABLE_ORDER "raised" (by Raised in the window, like the money chart) or "cash" or "ballot".
#   Total row: cash = cash_on_hand_total (below); raised = <window>_summary_raised_total, both over the same people.
SUMMARY_WEBSITE_LINK_KINDS = ["campaign", "office"]
SUMMARY_SKIP_FLAGGED_ACCOUNTS = True
SUMMARY_TABLE_ORDER = "raised"

# Per-race figures over candidates in the race, second filings by one person left out
# (duplicate_filing_of non-blank). "with_committee" = committees_added > 0.
# Plus <window>_summary_raised_total for each window (summary table total row; added 2026-11-14; A-1 gifts
# added for WINDOWS_PLUS_A1_GIFTS 2026-11-15).
RACE_STATS = ["candidates", "with_committee", "cash_on_hand_total"] + [f"{key}_summary_raised_total" for key, _ in WINDOWS]


def summary_raised_field(window_key):
    """Raised field used by the Summary, the chart and the race total for one window."""
    return f"{window_key}_raised_plus_a1_gifts" if window_key in WINDOWS_PLUS_A1_GIFTS else f"{window_key}_raised"

# ---------------------------------------------------------------------------


def records(frame):
    """Rows as dicts with blanks as None (JSON null)."""
    return frame.astype(object).where(frame.notna(), None).replace({"": None}).to_dict(orient="records")


def social_accounts(links):
    """Social rows for the page, with the settings above applied; prints what each one changed."""
    social = pd.read_csv(SOCIAL_ACCOUNTS_PATH, dtype=str, keep_default_na=False)
    if POST_AUTHORS_REVIEW_PATH.exists():
        review = pd.read_csv(POST_AUTHORS_REVIEW_PATH, dtype=str, keep_default_na=False)
        accepted = review[review["verdict"].str.strip().str.lower() == POST_AUTHOR_VERDICT_SHOWN]
        print(f"social: post authors reviewed {(review['verdict'] != '').sum()} of {len(review)}; "
              f"shown (verdict '{POST_AUTHOR_VERDICT_SHOWN}'): {len(accepted)}")
        social = pd.concat([social, pd.DataFrame({
            "candidate_id": accepted["candidate_id"], "raw_file": accepted["raw_file"], "retrieved": "",
            "found_as": "post_author", "platform": accepted["platform"], "account_label": accepted["handle"],
            "count_shown": "", "count_floor": "", "count_unit": "", "handle_in_recorded_links": "",
            "title_line": accepted["result_title"], "title_handle": "", "address_line": accepted["address_line"],
            "profile_url": accepted["likely_profile_url"]})], ignore_index=True)
    if SOCIAL_COLLAPSE_EXACT_REPEATS:
        before = len(social)
        social = social.drop_duplicates(["candidate_id", "platform", "account_label", "count_shown"])
        print(f"social: {before - len(social)} exact repeat rows collapsed ({before} -> {len(social)})")
    social_links = links[links["link_kind"] == "social"]
    def matching_url(row):
        label = row["account_label"]
        if not SOCIAL_LINK_IF_HANDLE_IN_URL or " " in label:
            return ""
        urls = social_links.loc[social_links["candidate_id"] == row["candidate_id"], "url"]
        hits = [url for url in urls if label.lower() in url.lower()]
        return hits[0] if hits else ""
    def built_url(row):
        if row["platform"] not in SOCIAL_PROFILE_URL_TEMPLATES:
            return ""
        handle_columns, url_pattern, handle_pattern = SOCIAL_PROFILE_URL_TEMPLATES[row["platform"]]
        for handle_column in handle_columns:
            if (handle_column == "title_handle" and SOCIAL_TITLE_HANDLE_ONLY_IF_TITLE_STARTS_WITH_LABEL
                    and not row["title_line"].startswith(row["account_label"])):
                continue
            handle = row[handle_column].strip().lstrip("@")
            if re.fullmatch(handle_pattern, handle):
                return url_pattern.format(handle=handle)
        return ""
    # URL order: a link we recorded; else the profile address Google showed (address-line rows,
    # extract_social_from_google.ADDRESS_LINE_RULES); else one built from the handle.
    recorded = social.apply(matching_url, axis=1)
    built = social.apply(built_url, axis=1)
    from_address = social["profile_url"]
    def basis(recorded_url, address_url, built_url_value):
        if recorded_url: return "recorded link"
        if address_url: return "address from Google's results"
        if built_url_value: return "built from the handle"
        return ""
    social = social.assign(
        url=recorded.where(recorded != "", from_address.where(from_address != "", built)),
        url_basis=[basis(r, a, b) for r, a, b in zip(recorded, from_address, built)])
    print(f"social: of {len(social)} accounts ({(social['found_as'] == 'address_line').sum()} from address lines, no count): "
          f"{social['url_basis'].replace('', 'not linked').value_counts().to_dict()}")
    print("social: not linked, by platform:", social.loc[social["url"] == "", "platform"].value_counts().to_dict())
    # Hand flags, matched on candidate + platform + handle (label or title handle, any case).
    flags = pd.read_csv(SOCIAL_FLAGS_PATH, dtype=str, keep_default_na=False)
    flag_text = {(row.candidate_id, row.platform, row.handle.lower()): row.flag for row in flags.itertuples()}
    def flag_for(row):
        for handle in (row["account_label"], row["title_handle"]):
            text = flag_text.get((row["candidate_id"], row["platform"], handle.lstrip("@").lower()))
            if text:
                return text
        return ""
    social = social.assign(flag=social.apply(flag_for, axis=1))
    unmatched = set(flag_text) - {(row["candidate_id"], row["platform"], handle.lstrip("@").lower())
                                  for _, row in social.iterrows() for handle in (row["account_label"], row["title_handle"])}
    print(f"social: flags {len(flag_text)}, matched {(social['flag'] != '').sum()}"
          + (f"; NOT matched: {sorted(unmatched)}" if unmatched else ""))
    return social[["candidate_id", "found_as", "platform", "account_label", "count_shown", "count_floor", "count_unit",
                   "handle_in_recorded_links", "url", "url_basis", "flag", "retrieved"]]


def between_markers(text, markers):
    """The text between a BEGIN marker's line end and the END marker (each must occur exactly once)."""
    begin, end = markers
    for marker in markers:
        if text.count(marker) != 1:
            raise SystemExit(f"{TEMPLATE_PATH.name}: marker {marker!r} found {text.count(marker)} times (need 1)")
    after_begin = text.split(begin, 1)[1]
    # Drop the rest of the BEGIN marker's line (its explanatory comment, which may run on to the next lines
    # for the CSS marker; that comment ends with "*/").
    if begin.startswith("/*"):
        after_begin = after_begin.split("*/", 1)[1]
    elif begin.startswith("<!--"):
        after_begin = after_begin.split("-->", 1)[1]
    else:
        after_begin = after_begin.split("\n", 1)[1]
        # The script marker's comment continues on "//" lines.
        while after_begin.startswith("//"):
            after_begin = after_begin.split("\n", 1)[1]
    return after_begin.split(end, 1)[0]


def write_embed_build(template, data):
    """docs/dashboard/app.js + docs/data/<EMBED_DATA_FILE> + docs/index.html (see EMBED_* settings)."""
    css = between_markers(template, APP_CSS_MARKERS)
    if not EMBED_DARK_MODE:
        dark_begin, dark_end = APP_DARK_MARKERS
        dark_block = dark_begin + css.split(dark_begin, 1)[1].split(dark_end, 1)[0] + dark_end
        css = css.replace(dark_block, "/* dark mode left out: EMBED_DARK_MODE = False in build_dashboard.py */")
        print("app.js: dark mode left out (EMBED_DARK_MODE = False)")
    markup = between_markers(template, APP_MARKUP_MARKERS)
    script = between_markers(template, APP_SCRIPT_MARKERS)
    app = f"""/* Chicago 2027 candidate dashboard, embeddable build. GENERATED by scripts/build_dashboard.py from
 * scripts/dashboard_template.html: do not edit here; edit the template and run `make dashboard`.
 *
 * Embed on any page:
 *   <div id="{EMBED_CONTAINER_ID}"></div>
 *   <script src="https://<user>.github.io/<repo>/dashboard/app.js"></script>
 * The script injects its CSS (scoped to #{EMBED_CONTAINER_ID}), draws the page markup into the div, then
 * fetches ../data/{EMBED_DATA_FILE} next to its own URL and draws the data.
 */
(function () {{
  'use strict';
  // Settings written by build_dashboard.py (EMBED_CONTAINER_ID, EMBED_DATA_FILE).
  const CONTAINER_ID = {json.dumps(EMBED_CONTAINER_ID)};
  const SCRIPT_URL = document.currentScript ? document.currentScript.src : window.location.href;
  const DATA_URL = new URL('../data/' + {json.dumps(EMBED_DATA_FILE)}, SCRIPT_URL).href;
  // Template pieces (between the APP_CSS / APP_MARKUP markers in dashboard_template.html).
  const CSS = {json.dumps(css, ensure_ascii=False)};
  const MARKUP = {json.dumps(markup, ensure_ascii=False)};

  const container = document.getElementById(CONTAINER_ID);
  if (!container) {{ console.error('candidate dashboard: no element with id ' + CONTAINER_ID); return; }}
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.append(style);
  container.innerHTML = MARKUP;

  fetch(DATA_URL)
    .then((response) => {{ if (!response.ok) throw new Error(response.status + ' ' + DATA_URL); return response.json(); }})
    .then(startDashboard)
    .catch((error) => {{
      console.error('candidate dashboard:', error);
      container.prepend(Object.assign(document.createElement('p'), {{ textContent: 'The dashboard did not load (' + error.message + '). Please reload the page.' }}));
    }});

  // The template's script (between the APP_SCRIPT markers), unchanged; DATA is the fetched JSON.
  function startDashboard(DATA) {{
{script}  }}
}})();
"""
    test_page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<style>body {{ margin: 0; }}</style>
</head>
<body>
<!-- GENERATED by scripts/build_dashboard.py. Local test page for the embedded build: the same two lines the
     website page uses (see the header of dashboard/app.js). -->
<div id="{EMBED_CONTAINER_ID}"></div>
<script src="dashboard/app.js"></script>
</body>
</html>
"""
    for path, text in [(EMBED_APP_PATH, app), (EMBED_DATA_PATH, json.dumps(data, ensure_ascii=False)),
                       (EMBED_TEST_PAGE_PATH, test_page)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({path.stat().st_size:,} bytes)")


def main():
    candidates = pd.read_csv(CANDIDATES_PATH, dtype=str, keep_default_na=False)
    committees = pd.read_csv(COMMITTEES_PATH, dtype=str, keep_default_na=False)
    if not SHOW_SECOND_FILINGS:
        second_filings = candidates[candidates["duplicate_filing_of"] != ""]
        print(f"second filings left off the page (SHOW_SECOND_FILINGS = False): "
              f"{second_filings[['candidate_id', 'duplicate_filing_of']].values.tolist()}")
        candidates = candidates[candidates["duplicate_filing_of"] == ""]
        committees = committees[committees["candidate_id"].isin(set(candidates["candidate_id"]))]

    people = candidates[candidates["duplicate_filing_of"] == ""]
    race_stats = people.groupby("race_key").agg(
        candidates=("candidate_id", "size"),
        with_committee=("committees_added", lambda values: int((values.astype(int) > 0).sum())),
        cash_on_hand_total=("cash_on_hand", lambda values: pd.to_numeric(values, errors="coerce").fillna(0).sum()),
        **{f"{key}_summary_raised_total": (summary_raised_field(key),
                                           lambda values: pd.to_numeric(values, errors="coerce").fillna(0).sum())
           for key, _ in WINDOWS},
    ).reset_index()
    races = candidates.drop_duplicates("race_key")[["race_key", "race_label", "race_order"]]
    races = races.assign(race_order=races["race_order"].astype(int)).sort_values("race_order")
    races = races.merge(race_stats, on="race_key", how="left")

    incumbents = pd.read_csv(INCUMBENTS_PATH, dtype=str, keep_default_na=False)
    links = pd.read_csv(LINKS_PATH, dtype=str, keep_default_na=False)
    top_donors = pd.read_csv(TOP_DONORS_PATH, dtype=str, keep_default_na=False)
    social = social_accounts(links)
    # Candidates the Google pass has searched (date = checked_on): tells "none shown" from "not searched yet".
    # With the social rerun (2026-11-14) a candidate can have two searches; the latest date is shown.
    google_pass = pd.concat([pd.read_csv(path, dtype=str, keep_default_na=False)
                             for path in GOOGLE_PASS_PATHS if path.exists()])
    social_searched = google_pass.groupby("candidate_id")["checked_on"].max().to_dict()
    all_endorsements = pd.read_csv(ENDORSEMENTS_PATH, dtype=str, keep_default_na=False)
    all_endorsements = all_endorsements[all_endorsements["match_status"].isin(ENDORSEMENT_PAGE_MATCH_STATUSES)]
    # candidate_id here = the proposed match (the input column of the same name is only the hand-given id).
    all_endorsements = all_endorsements.drop(columns=["candidate_id"]).rename(columns={"candidate_id_proposed": "candidate_id"})
    # Local page vs published page differ only in which review statuses are shown (settings above).
    endorsements = all_endorsements[all_endorsements["review_status"].isin(ENDORSEMENT_PAGE_REVIEW_STATUSES)]
    embed_endorsements = all_endorsements[all_endorsements["review_status"].isin(EMBED_ENDORSEMENT_PAGE_REVIEW_STATUSES)]
    print(f"endorsements shown: local page {len(endorsements)} rows (review_status {ENDORSEMENT_PAGE_REVIEW_STATUSES}); "
          f"published page {len(embed_endorsements)} rows ({EMBED_ENDORSEMENT_PAGE_REVIEW_STATUSES})")
    shown_ids = set(candidates["candidate_id"])
    for name, frame in [("incumbents", incumbents), ("links", links), ("top donors", top_donors), ("social", social),
                        ("endorsements", endorsements)]:
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
        "reports_through_short": REPORTS_THROUGH_SHORT,
        "candidate_list_checked": candidate_list_checked_label(),
        "candidate_list_status_note": CANDIDATE_LIST_STATUS_NOTE,
        "isbe_download": isbe_download_label(),
        "feedback": {"form_url": FEEDBACK_FORM_URL, "form_prefill_url": FEEDBACK_FORM_PREFILL_URL,
                     "github_issues_url": GITHUB_ISSUES_URL, "contact_email": CONTACT_EMAIL},
        "committee_source_links": [{"label": label, "url": url, "description": description}
                                   for label, url, description in COMMITTEE_SOURCE_LINKS],
        "data_sources": [{"name": name, "url": url, "use": use} for name, url, use in DATA_SOURCES],
        "sunshine_style_cutoff": SUNSHINE_STYLE_SHOWN_IF_FIRST_REPORT_ON_OR_AFTER,
        "default_race": DEFAULT_RACE_KEY,
        "windows": [{"key": key, "label": label, "summary_raised_field": summary_raised_field(key),
                     "adds_a1_gifts": key in WINDOWS_PLUS_A1_GIFTS} for key, label in WINDOWS],
        "candidate_columns": [{"column": column, "header": header, "description": description, "format": fmt}
                              for column, header, description, fmt in CANDIDATE_COLUMNS],
        "incumbent_as_of": INCUMBENT_AS_OF_LABEL,
        "link_kind_labels": LINK_KIND_LABELS,
        "incumbents": records(incumbents[["candidate_id", "officeholder_name", "source_url"]]),
        "links": records(links[["candidate_id", "link_kind", "platform", "url", "found_by", "source_statuses"]]),
        "top_donors": records(top_donors),
        "social": records(social),
        "social_searched": social_searched,
        "social_platform_order": SOCIAL_PLATFORM_ORDER,
        "social_table_order": SOCIAL_TABLE_ORDER,
        "money_chart_order": MONEY_CHART_ORDER,
        "summary": {"website_link_kinds": SUMMARY_WEBSITE_LINK_KINDS, "skip_flagged_accounts": SUMMARY_SKIP_FLAGGED_ACCOUNTS,
                    "order": SUMMARY_TABLE_ORDER},
        "endorsements": records(endorsements[["candidate_id"] + ENDORSEMENT_PAGE_COLUMNS[1:]]),
        "endorser_type_labels": ENDORSER_TYPE_LABELS,
        "races": records(races),
        "candidates": records(candidates),
        "committees": records(committees),
    }
    template = TEMPLATE_PATH.read_text()
    if DATA_PLACEHOLDER not in template:
        raise SystemExit(f"{TEMPLATE_PATH.name} has no {DATA_PLACEHOLDER} placeholder")
    for placeholder, value in TEMPLATE_TEXT_PLACEHOLDERS.items():
        if placeholder not in template:
            raise SystemExit(f"{TEMPLATE_PATH.name} has no {placeholder} placeholder")
        template = template.replace(placeholder, value)
    page = template.replace(DATA_PLACEHOLDER, json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page)
    if WRITE_EMBED_BUILD:
        embed_data = {**data, "endorsements": records(embed_endorsements[["candidate_id"] + ENDORSEMENT_PAGE_COLUMNS[1:]])}
        write_embed_build(template, embed_data)

    print(f"{len(races)} races, {len(candidates)} candidate rows, {len(committees)} committee rows")
    print("per-race figures (check against display_candidates.csv):")
    print(races[["race_label", *RACE_STATS]].to_string(index=False))
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} — open it in a browser")


if __name__ == "__main__":
    main()
