"""Pull social media accounts and follower counts out of saved Google results pages.

Input:
  data/raw/google_search/<candidate_id>.txt (and <candidate_id>_2.txt): Google results page text,
      saved by the Google pass agents (first lines "query:", "url:", "retrieved:").
  data/endorsements/candidate_campaign_sites_google.csv: to mark accounts that the candidate's
      own campaign site links to (other_site_urls / notes of that row).

Output:
  data/endorsements/social_accounts_google.csv, one row per (raw file, account shown).
  Regenerated every run; nothing is chosen or dropped, only parsed.

What Google shows (seen 2026-11-12 in 44 of 62 raw files), two lines per account:
    Instagram · billfor1st
    490+ followers
Counts are Google's rounded figures ("2.2K+"), as of the retrieval date, and Google's copy may be
older than the platform's own number. Exact counts sometimes appear in the snippet text
("498 followers"); those are not parsed (OPEN QUESTION: worth parsing?).

Matching an account to a candidate is NOT decided here. Column linked_from_campaign_site says
whether the account's handle appears in the URLs the Google pass recorded for that candidate
(the agents record social links taken from the candidate's site and from the results). An account
shown only in search results may be personal, official (alderman's office), campaign, or a
same-named person: the column account_label is Google's text, kept raw for review.

Usage:
  python scripts/extract_social_from_google.py
"""

import csv
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIRECTORY = REPO_ROOT / "data/raw/google_search"
GOOGLE_SITES_FILE = REPO_ROOT / "data/endorsements/candidate_campaign_sites_google.csv"
OUTPUT_FILE = REPO_ROOT / "data/endorsements/social_accounts_google.csv"

# Platform names as Google prints them before " · ". Bluesky was not seen in Google results on
# 2026-11-12; it is listed in case it appears.
PLATFORMS = ["Instagram", "Facebook", "X", "TikTok", "LinkedIn", "YouTube", "Threads", "Bluesky"]

# "Instagram · billfor1st" then, on the next line, "490+ followers" (or subscribers for YouTube).
ACCOUNT_PATTERN = re.compile(
    r"^(?P<platform>" + "|".join(PLATFORMS) + r") · (?P<label>[^\n]+)\n"
    r"(?P<count>[\d.,]+\s*[KM]?\+?) (?P<unit>followers|subscribers)",
    re.MULTILINE,
)

# "2.2K+" -> 2200, "490+" -> 490, "1M+" -> 1000000. The "+" means "at least", so this is a floor.
COUNT_MULTIPLIERS = {"": 1, "K": 1_000, "M": 1_000_000}

OUTPUT_COLUMNS = [
    "candidate_id", "raw_file", "retrieved", "platform", "account_label",
    "count_shown", "count_floor", "count_unit", "linked_from_campaign_site",
]


def count_floor(count_text):
    """Google's rounded count as a number (lower bound): '2.2K+' -> 2200."""
    match = re.match(r"([\d.,]+)\s*([KM]?)", count_text)
    number = float(match.group(1).replace(",", ""))
    return int(round(number * COUNT_MULTIPLIERS[match.group(2)]))


def read_header(text):
    """The 'retrieved:' line written by the Google pass ('' if missing)."""
    match = re.search(r"^retrieved:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def main():
    recorded_urls = {}
    if GOOGLE_SITES_FILE.exists():
        with open(GOOGLE_SITES_FILE, newline="") as sites_file:
            for row in csv.DictReader(sites_file):
                recorded_urls[row["candidate_id"]] = " ".join(
                    row.get(column, "") for column in ("other_site_urls", "notes", "campaign_site_note")).lower()

    output_rows = []
    for raw_path in sorted(RAW_DIRECTORY.glob("*.txt")):
        candidate_id = re.sub(r"_\d+$", "", raw_path.stem)
        text = raw_path.read_text(errors="replace")
        for match in ACCOUNT_PATTERN.finditer(text):
            label = match.group("label").strip()
            # Handle-like labels (no spaces) are checked against the URLs recorded for the candidate.
            linked = (" " not in label) and (label.lower() in recorded_urls.get(candidate_id, ""))
            output_rows.append({
                "candidate_id": candidate_id,
                "raw_file": raw_path.name,
                "retrieved": read_header(text),
                "platform": match.group("platform"),
                "account_label": label,
                "count_shown": match.group("count").strip(),
                "count_floor": count_floor(match.group("count")),
                "count_unit": match.group("unit"),
                "linked_from_campaign_site": linked,
            })

    with open(OUTPUT_FILE, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    candidates = {row["candidate_id"] for row in output_rows}
    print(f"raw files: {len(list(RAW_DIRECTORY.glob('*.txt')))}; accounts parsed: {len(output_rows)} "
          f"for {len(candidates)} candidates")
    by_platform = {}
    for row in output_rows:
        by_platform[row["platform"]] = by_platform.get(row["platform"], 0) + 1
    print(f"by platform: {by_platform}")
    print(f"handle found in the candidate's recorded URLs: {sum(row['linked_from_campaign_site'] for row in output_rows)}")
    print(f"wrote {OUTPUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
