"""One table of every web link found for each candidate: campaign site, office site, social
accounts, fundraising pages, endorsement pages.

Every link from every source is kept (user, 2026-11-12: "we display all of them"). When the
same link was found by more than one source, it appears once and `found_by` names all of them.
SOURCE_ORDER only sets the order links are listed in. Nothing here decides a link is right:
the pass files are unreviewed (review_status), and visitors can check each link by hand.

Inputs (all in data/endorsements/):
  campaign_sites_user_provided.csv     sites the user gave (site_url, site_kind)
  candidate_campaign_sites_google.csv  second pass, Google in Chrome (62 of 161 on 2026-11-12)
  candidate_campaign_sites.csv         first pass, agent search tool (161 rows)
Output:
  data/tables/candidate_links.csv      one row per candidate x link (columns at OUTPUT_COLUMNS)

Rerun after each Google chunk; new rows flow through with no code change.

Usage:
  python scripts/build_candidate_links.py
"""

import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
ENDORSEMENTS_DIR = REPO_ROOT / "data" / "endorsements"
OUTPUT_PATH = REPO_ROOT / "data" / "tables" / "candidate_links.csv"

# Sources, in listing order (user, 2026-11-12: user > google > first pass).
#   (source name, file, kind of file)
SOURCE_ORDER = [
    ("user", ENDORSEMENTS_DIR / "campaign_sites_user_provided.csv", "user_file"),
    ("google", ENDORSEMENTS_DIR / "candidate_campaign_sites_google.csv", "pass_file"),
    ("first_pass", ENDORSEMENTS_DIR / "candidate_campaign_sites.csv", "pass_file"),
]

# Pass-file URL columns -> the kind of link the agent said it was, and the note column
# written next to it.
PASS_FILE_URL_COLUMNS = {
    "campaign_site_url": ("campaign", "campaign_site_note"),
    "ward_office_url": ("office", "ward_office_note"),
    "endorsements_url": ("endorsements", ""),
    "other_site_urls": ("other", "other_site_note"),
}
# User file site_kind -> link kind.
USER_SITE_KINDS = {"campaign": "campaign", "ward_office": "office", "social": "social"}  # "social" added 2026-11-13

# LINK_KIND_RULE "domain_first": a link on one of these domains gets the domain's kind
# whatever column it was in (e.g. a Facebook page entered as a campaign site is "social").
# Other links keep the column's kind. Fundraising pages are their own kind (user, 2026-11-12:
# shown, but not counted as a campaign site). Add domains here as they turn up.
SOCIAL_DOMAINS = {
    "facebook.com": "Facebook", "instagram.com": "Instagram", "x.com": "X", "twitter.com": "X",
    "tiktok.com": "TikTok", "youtube.com": "YouTube", "bsky.app": "Bluesky", "linkedin.com": "LinkedIn",
    "threads.net": "Threads", "threads.com": "Threads", "meetup.com": "Meetup",
}
FUNDRAISING_DOMAINS = {
    "actblue.com": "ActBlue", "winred.com": "WinRed", "crowdblue.com": "CrowdBlue",
    "donorbox.org": "Donorbox", "fundhero.com": "FundHero", "anedot.com": "Anedot",
    # added 2026-11-12 after the first run listed them as "other"
    "democracyengine.com": "Democracy Engine", "zeffy.com": "Zeffy",
}
LINK_KIND_RULE = "domain_first"

# Listing order of link kinds on the page.
LINK_KIND_ORDER = ["campaign", "office", "social", "fundraising", "endorsements", "other"]

# A URL inside a cell: with a scheme, or a bare domain like 'illinoisfordowell.com' (gets https://).
# Cells are split on ';' first. Text that is not a URL (agent notes like "(as '@aldmosley21')")
# is printed, not kept.
URL_PATTERN = re.compile(r"https?://[^\s;,()']+|(?<![@\w.])(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|us|info|gov|io|co)(?:/[^\s;,()']*)?",
                         flags=re.IGNORECASE)

OUTPUT_COLUMNS = ["candidate_id", "link_kind", "platform", "url", "found_by", "first_source",
                  "source_columns", "source_statuses", "first_source_note"]

# ---------------------------------------------------------------------------


def link_key(url):
    """Same-link test: lowercase, no scheme, no 'www.', no trailing slash."""
    key = re.sub(r"^https?://", "", url.strip().lower())
    key = re.sub(r"^www\.", "", key)
    return key.rstrip("/")


def domain_of(url):
    """'https://secure.actblue.com/donate/x' -> 'secure.actblue.com'."""
    return re.sub(r"^https?://", "", url.lower()).split("/")[0]


def classify(url, column_kind):
    """(link_kind, platform) under LINK_KIND_RULE."""
    domain = domain_of(url)
    for known, platform in SOCIAL_DOMAINS.items():
        if domain == known or domain.endswith("." + known):
            return "social", platform
    for known, platform in FUNDRAISING_DOMAINS.items():
        if domain == known or domain.endswith("." + known):
            return "fundraising", platform
    return column_kind, ""


def urls_in_cell(cell, where, leftovers):
    """URLs in one cell; any other text is recorded in leftovers for printing."""
    found = []
    for part in cell.split(";"):
        part = part.strip()
        if not part:
            continue
        matches = URL_PATTERN.findall(part)
        rest = URL_PATTERN.sub("", part).strip(" ,")
        if rest:
            leftovers.append(f"{where}: kept {matches or 'nothing'}, ignored text '{rest}'")
        found += [match if match.lower().startswith("http") else "https://" + match for match in matches]
    return found


def source_rows(source, path, file_kind, leftovers):
    """Every link in one source file, one dict per link."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    rows = []
    for record in frame.to_dict(orient="records"):
        if file_kind == "user_file":
            column_kind = USER_SITE_KINDS[record["site_kind"]]
            for url in urls_in_cell(record["site_url"], f"{source} {record['candidate_id']} site_url", leftovers):
                rows.append({"candidate_id": record["candidate_id"], "url": url, "source": source,
                             "column_kind": column_kind, "source_column": "site_url",
                             "status": "given_by_user", "note": record["notes"]})
            continue
        for column, (column_kind, note_column) in PASS_FILE_URL_COLUMNS.items():
            for url in urls_in_cell(record[column], f"{source} {record['candidate_id']} {column}", leftovers):
                rows.append({"candidate_id": record["candidate_id"], "url": url, "source": source,
                             "column_kind": column_kind, "source_column": column,
                             "status": f"{record['status']}/{record['review_status']}",
                             "note": record.get(note_column, "") if note_column else ""})
    return rows


def main():
    leftovers = []
    raw = []
    for source, path, file_kind in SOURCE_ORDER:
        rows = source_rows(source, path, file_kind, leftovers)
        print(f"{source}: {len(rows)} links from {path.relative_to(REPO_ROOT)}")
        raw += rows
    links = pd.DataFrame(raw)
    links["source_rank"] = links["source"].map({name: rank for rank, (name, _, _) in enumerate(SOURCE_ORDER)})
    links["key"] = links["url"].map(link_key)
    kinds = links.apply(lambda row: classify(row["url"], row["column_kind"]), axis=1)
    links["link_kind"] = [kind for kind, _ in kinds]
    links["platform"] = [platform for _, platform in kinds]

    # One row per candidate x link; the first source (SOURCE_ORDER) gives the URL spelling and note.
    links = links.sort_values(["candidate_id", "source_rank"])
    grouped = links.groupby(["candidate_id", "key"], sort=False)
    combined = grouped.first().reset_index()
    combined["found_by"] = grouped["source"].agg(lambda values: "; ".join(dict.fromkeys(values))).values
    combined["source_columns"] = grouped["source_column"].agg(lambda values: "; ".join(dict.fromkeys(values))).values
    combined["source_statuses"] = grouped["status"].agg(lambda values: "; ".join(dict.fromkeys(values))).values
    combined = combined.rename(columns={"source": "first_source", "note": "first_source_note"})
    # A link entered under two kinds (e.g. campaign in one pass, office in the other) is printed.
    kind_conflicts = links.groupby(["candidate_id", "key"])["link_kind"].nunique()
    for (candidate_id, key), _ in kind_conflicts[kind_conflicts > 1].items():
        kinds_seen = links[(links.candidate_id == candidate_id) & (links.key == key)][["source", "link_kind"]].values.tolist()
        print(f"  kind differs by source: {candidate_id} {key}: {kinds_seen} (first source's kind used)")

    combined["kind_order"] = combined["link_kind"].map({kind: order for order, kind in enumerate(LINK_KIND_ORDER)})
    combined = combined.sort_values(["candidate_id", "kind_order", "source_rank"])[OUTPUT_COLUMNS]
    combined.to_csv(OUTPUT_PATH, index=False)

    print(f"text in URL cells that is not a URL ({len(leftovers)}; ignored):")
    for line in leftovers:
        print("  " + line)
    print(f"{len(combined)} links for {combined['candidate_id'].nunique()} candidates "
          f"(LINK_KIND_RULE={LINK_KIND_RULE}); by kind: {combined['link_kind'].value_counts().to_dict()}")
    print(f"found by more than one source: {int(combined['found_by'].str.contains(';').sum())}")
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
