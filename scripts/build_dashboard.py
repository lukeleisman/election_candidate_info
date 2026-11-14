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
  dashboard/index.html

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
GOOGLE_PASS_PATH = REPO_ROOT / "data" / "endorsements" / "candidate_campaign_sites_google.csv"
# Hand-edited (user, 2026-11-13): flags on single accounts, shown next to the account on the page
# (e.g. "May not be this candidate"; later "Verified"). Key: candidate_id + platform + handle (any case).
SOCIAL_FLAGS_PATH = REPO_ROOT / "data" / "endorsements" / "social_account_flags.csv"
# Hand-edited review of post authors (extract_social_from_google.POST_AUTHORS_REVIEW_FILE).
POST_AUTHORS_REVIEW_PATH = REPO_ROOT / "data" / "endorsements" / "social_post_authors_review.csv"
# Endorsement rows with their proposed candidate match (scripts/match_endorsements.py).
ENDORSEMENTS_PATH = REPO_ROOT / "data" / "endorsements" / "endorsements.csv"
# Which endorsement rows the page shows, by review_status. PLAN.md §4 says reviewed rows only.
# Set 2026-11-14 to also show unreviewed rows, each tagged "Not checked yet", while the page is local
# and review is starting. User 2026-11-14: keep showing unreviewed rows until the page is published; then
# switch to ["reviewed"].
ENDORSEMENT_PAGE_REVIEW_STATUSES = ["reviewed", "unreviewed"]
# Which match statuses are shown. judgment_call rows are tagged "Name match not confirmed".
ENDORSEMENT_PAGE_MATCH_STATUSES = ["accepted", "judgment_call"]
# Endorser type labels on the page (keys = match_endorsements.ENDORSER_TYPES).
ENDORSER_TYPE_LABELS = {"union": "Union", "advocacy_org": "Advocacy group", "political_org": "Political group",
                        "party_or_ward_org": "Party / ward org", "elected_official": "Elected official",
                        "former_official": "Former official", "newspaper": "Newspaper",
                        "business_org": "Business group", "person": "Person"}
ENDORSEMENT_PAGE_COLUMNS = ["candidate_id_proposed", "endorser_name", "endorser_type", "cycle", "url",
                            "announced_on", "seen_on", "review_status", "match_status"]
TEMPLATE_PATH = REPO_ROOT / "scripts" / "dashboard_template.html"
OUTPUT_PATH = REPO_ROOT / "dashboard" / "index.html"

# Placeholder in the template that the data JSON replaces.
DATA_PLACEHOLDER = "/*DASHBOARD_DATA*/null"

# Page title and the sentence under it (user, 2026-11-13: general, not money-only). Placed into the
# template's __PAGE_TITLE__ / __PAGE_DESCRIPTION__. Money-specific dates moved to the money section.
PAGE_TITLE = "Chicago 2027 Candidate Information"
# Description wording: the user's own text (2026-11-13).
PAGE_DESCRIPTION = ("This page exists to assist in evaluating races in Chicago's February 23, 2027 municipal "
                    "election (mayor, clerk, treasurer and the 50 aldermanic races). It collects information "
                    "like funds raised, endorsements, social media following and web presence for filed "
                    "candidates in each race.")
TEMPLATE_TEXT_PLACEHOLDERS = {"__PAGE_TITLE__": PAGE_TITLE, "__PAGE_DESCRIPTION__": PAGE_DESCRIPTION}

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
    social = social_accounts(links)
    # Candidates the Google pass has searched (date = checked_on): tells "none shown" from "not searched yet".
    google_pass = pd.read_csv(GOOGLE_PASS_PATH, dtype=str, keep_default_na=False)
    social_searched = dict(zip(google_pass["candidate_id"], google_pass["checked_on"]))
    endorsements = pd.read_csv(ENDORSEMENTS_PATH, dtype=str, keep_default_na=False)
    endorsements = endorsements[endorsements["review_status"].isin(ENDORSEMENT_PAGE_REVIEW_STATUSES)
                                & endorsements["match_status"].isin(ENDORSEMENT_PAGE_MATCH_STATUSES)]
    # candidate_id here = the proposed match (the input column of the same name is only the hand-given id).
    endorsements = endorsements.drop(columns=["candidate_id"]).rename(columns={"candidate_id_proposed": "candidate_id"})
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
        "social": records(social),
        "social_searched": social_searched,
        "social_platform_order": SOCIAL_PLATFORM_ORDER,
        "social_table_order": SOCIAL_TABLE_ORDER,
        "money_chart_order": MONEY_CHART_ORDER,
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

    print(f"{len(races)} races, {len(candidates)} candidate rows, {len(committees)} committee rows")
    print("per-race figures (check against display_candidates.csv):")
    print(races[["race_label", *RACE_STATS]].to_string(index=False))
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} — open it in a browser")


if __name__ == "__main__":
    main()
