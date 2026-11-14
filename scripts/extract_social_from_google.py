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

Matching an account to a candidate is NOT decided here. Column handle_in_recorded_links (renamed 2026-11-13 from linked_from_campaign_site, which overstated it) says
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
# Hand-edited review file (user, 2026-11-13): accounts seen only as the AUTHOR of a post ("account › posts ›
# ..."), skipped by ADDRESS_LINE_RULES, listed for the user to verify. This script only ADDS new rows
# (key: candidate_id + platform + handle); it never changes a row already there, so verdicts are kept.
# verdict: blank = not reviewed; "candidate" = the candidate's own account (then shown on the page);
# "not candidate" = someone else's.
POST_AUTHORS_REVIEW_FILE = REPO_ROOT / "data/endorsements/social_post_authors_review.csv"
POST_AUTHORS_REVIEW_COLUMNS = ["candidate_id", "ballot_name", "platform", "handle", "verdict", "reviewer_notes",
                               "likely_profile_url", "address_line", "result_title", "snippet", "raw_file"]
CANDIDATES_FILE = REPO_ROOT / "data/candidates/candidates_cboe.csv"

# Platform names as Google prints them before " · ". Bluesky was not seen in Google results on
# 2026-11-12; it is listed in case it appears.
PLATFORMS = ["Instagram", "Facebook", "X", "TikTok", "LinkedIn", "YouTube", "Threads", "Bluesky"]

# "Instagram · billfor1st" then, on the next line, "490+ followers" (or subscribers for YouTube).
ACCOUNT_PATTERN = re.compile(
    r"^(?P<platform>" + "|".join(PLATFORMS) + r") · (?P<label>[^\n]+)\n"
    r"(?P<count>[\d.,]+\s*[KM]?\+?) (?P<unit>followers|subscribers)",
    re.MULTILINE,
)

# The result title is the last non-blank line BEFORE "Platform · label" (seen 2026-11-13 in ALD-01-001,
# MAYOR-00-001: "Alderman La Spata 1st Ward (@The1stWard)" then a blank line, then "Facebook · ...").
# Facebook titles often carry the page's handle as "(@handle)"; it is kept in title_handle so the page can
# link the account (Facebook labels are display names, not handles). OPEN QUESTION: the title could in
# principle belong to the previous result if Google ever drops a title; spot-check title_line.
TITLE_HANDLE_PATTERN = re.compile(r"\(@([A-Za-z0-9._-]+)\)")

# "2.2K+" -> 2200, "490+" -> 490, "1M+" -> 1000000. The "+" means "at least", so this is a floor.
COUNT_MULTIPLIERS = {"": 1, "K": 1_000, "M": 1_000_000}

# Address lines (added 2026-11-13, user: "I want links, even if there isn't a follower count"). Ordinary
# results show their address as "https://www.instagram.com › nubiafor25". When that address is a PROFILE,
# the account is kept as a row with found_as = "address_line", no count, and profile_url built from it.
# Rules, per platform: (domain pattern, segments before the handle, accepted segments AFTER the handle,
# reserved words that are never a handle, handle pattern).
#   - "account › posts › ..." is a post BY that account, which is often not the candidate (seen: GreenStarMovement,
#     growingupinillinois for other candidates), so only profile pages and profile tabs are accepted.
#   - A segment shortened by Google ("...", "…") is never used.
ADDRESS_LINE_PATTERN = re.compile(r"^https?://(?:www\.|m\.)?(?P<domain>[a-z.]+) › (?P<path>.+)$", re.MULTILINE)
ADDRESS_LINE_RULES = {
    "Instagram": (r"instagram\.com", [], set(),
                  {"reel", "reels", "p", "popular", "explore", "stories", "tv"}, r"[A-Za-z0-9._]+"),
    "Facebook": (r"facebook\.com", [], {"mentions", "videos", "photos", "about", "reels"},
                 {"posts", "photos", "mentions", "videos", "groups", "fb-answers", "public", "watch", "reel", "events",
                  "pages", "people", "story.php", "permalink.php", "hashtag", "profile.php", "share"},
                 r"[A-Za-z0-9.]+"),
    "X": (r"(x|twitter)\.com", [], set(), {"search", "hashtag", "i", "status"}, r"@?[A-Za-z0-9_]+"),
    "Threads": (r"threads\.(com|net)", [], set(), set(), r"@[A-Za-z0-9._]+"),
    "TikTok": (r"tiktok\.com", [], set(), {"discover", "tag"}, r"@[A-Za-z0-9._]+"),
    "LinkedIn": (r"linkedin\.com", ["in"], set(), set(), r"[A-Za-z0-9-]+"),
    "Bluesky": (r"bsky\.app", ["profile"], set(), {"post"}, r"[A-Za-z0-9.-]+"),
}
# Profile URL for each platform, from the handle in the address line.
ADDRESS_PROFILE_URLS = {
    "Instagram": "https://www.instagram.com/{handle}/", "Facebook": "https://www.facebook.com/{handle}",
    "X": "https://x.com/{handle}", "Threads": "https://www.threads.net/{handle}",
    "TikTok": "https://www.tiktok.com/{handle}", "LinkedIn": "https://www.linkedin.com/in/{handle}/",
    "Bluesky": "https://bsky.app/profile/{handle}",
}

# Links section (added 2026-11-13; raw files from chunk 6 on, ALD-31-003 first): after this marker, one line
# per link in Google's results, "URL | link text" (URL = origin + path; " [query/fragment dropped]" when
# Google's link had a query string). Used two ways:
#   1. An account box ("Facebook · Name" + followers) gets the exact URL of the link whose text contains
#      "Platform · label" (card_link_url); if that URL is a profile, it becomes profile_url.
#   2. Profile links not already listed become rows with found_as = "result_link" (no count); post links
#      go to the post-author review file. Same ADDRESS_LINE_RULES as address lines.
LINKS_SECTION_MARKER = "--- Links (href | link text) ---"
LINK_LINE_PATTERN = re.compile(r"^(?P<url>https?://\S+)(?P<dropped> \[query/fragment dropped\])? \| (?P<text>.*)$", re.MULTILINE)

OUTPUT_COLUMNS = [
    "candidate_id", "raw_file", "retrieved", "found_as", "platform", "account_label",
    "count_shown", "count_floor", "count_unit", "handle_in_recorded_links", "title_line", "title_handle",
    "address_line", "profile_url", "card_link_url",
]


def profile_from_url(url):
    """profile_from_address() for a full URL: path segments joined the way Google displays them."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    domain = re.sub(r"^(www\.|m\.)", "", parts.netloc.lower())
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return None, None
    return profile_from_address(domain, " › ".join(segments))


def profile_from_address(domain, path):
    """(platform, handle) when the address line is a profile page, else (None, reason skipped)."""
    for platform, (domain_pattern, before, tabs, reserved, handle_pattern) in ADDRESS_LINE_RULES.items():
        if not re.fullmatch(domain_pattern, domain):
            continue
        segments = [segment.strip() for segment in path.split(" › ")]
        if segments[:len(before)] != before or len(segments) <= len(before):
            return None, f"{platform}: not a profile address"
        handle, after = segments[len(before)], segments[len(before) + 1:]
        if "..." in handle or "…" in handle:
            return None, f"{platform}: handle shortened by Google"
        if handle.lower() in reserved:
            return None, f"{platform}: '{handle}' is not an account"
        if not re.fullmatch(handle_pattern, handle):
            return None, f"{platform}: '{handle}' does not look like a handle"
        if after and not (len(after) == 1 and after[0].lower() in tabs):
            return None, f"{platform}: a page under the account (e.g. a post), not the profile|{handle}"
        return platform, handle
    return None, None  # not a social site


def title_before(text, start):
    """Last non-blank line before position start (the search result's title), or ''."""
    lines = [line.strip() for line in text[:start].splitlines() if line.strip()]
    return lines[-1] if lines else ""


def count_floor(count_text):
    """Google's rounded count as a number (lower bound): '2.2K+' -> 2200."""
    match = re.match(r"([\d.,]+)\s*([KM]?)", count_text)
    number = float(match.group(1).replace(",", ""))
    return int(round(number * COUNT_MULTIPLIERS[match.group(2)]))


def read_header(text):
    """The 'retrieved:' line written by the Google pass ('' if missing)."""
    match = re.search(r"^retrieved:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def update_post_authors_review(post_authors):
    """Add post authors not yet in the review file; keep every existing row (and its verdict) as is."""
    existing = []
    if POST_AUTHORS_REVIEW_FILE.exists():
        with open(POST_AUTHORS_REVIEW_FILE, newline="") as review_file:
            existing = list(csv.DictReader(review_file))
    known = {(row["candidate_id"], row["platform"], row["handle"].lower()) for row in existing}
    with open(CANDIDATES_FILE, newline="") as candidates_file:
        names = {row["candidate_id"]: row["ballot_name_raw"] for row in csv.DictReader(candidates_file)}
    added = []
    for row in post_authors:
        key = (row["candidate_id"], row["platform"], row["handle"].lower())
        if key in known:
            continue
        known.add(key)
        added.append({**row, "ballot_name": names.get(row["candidate_id"], ""), "verdict": "", "reviewer_notes": ""})
    with open(POST_AUTHORS_REVIEW_FILE, "w", newline="") as review_file:
        writer = csv.DictWriter(review_file, fieldnames=POST_AUTHORS_REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(existing + added)
    print(f"post authors for review: {len(existing)} already listed, {len(added)} added -> "
          f"{POST_AUTHORS_REVIEW_FILE.relative_to(REPO_ROOT)}")


def main():
    recorded_urls = {}
    if GOOGLE_SITES_FILE.exists():
        with open(GOOGLE_SITES_FILE, newline="") as sites_file:
            for row in csv.DictReader(sites_file):
                recorded_urls[row["candidate_id"]] = " ".join(
                    row.get(column, "") for column in ("other_site_urls", "notes", "campaign_site_note")).lower()

    output_rows = []
    skipped_address_lines = []
    post_authors = []
    for raw_path in sorted(RAW_DIRECTORY.glob("*.txt")):
        candidate_id = re.sub(r"_\d+$", "", raw_path.stem)
        full_text = raw_path.read_text(errors="replace")
        # Page text and links section are parsed separately.
        text, _, links_text = full_text.partition(LINKS_SECTION_MARKER)
        links = [(match.group("url"), match.group("text")) for match in LINK_LINE_PATTERN.finditer(links_text)]
        for match in ACCOUNT_PATTERN.finditer(text):
            label = match.group("label").strip()
            title_line = title_before(text, match.start())
            title_handle_match = TITLE_HANDLE_PATTERN.search(title_line)
            # Handle-like labels (no spaces) are checked against the URLs recorded for the candidate.
            linked = (" " not in label) and (label.lower() in recorded_urls.get(candidate_id, ""))
            # Exact link of this account box, from the links section (first link whose text names it).
            card_link = next((url for url, link_text in links
                              if f"{match.group('platform')} · {label}" in link_text), "")
            card_platform, card_handle = profile_from_url(card_link) if card_link else (None, None)
            output_rows.append({
                "candidate_id": candidate_id,
                "raw_file": raw_path.name,
                "retrieved": read_header(text),
                "platform": match.group("platform"),
                "account_label": label,
                "count_shown": match.group("count").strip(),
                "count_floor": count_floor(match.group("count")),
                "count_unit": match.group("unit"),
                "handle_in_recorded_links": linked,
                "title_line": title_line,
                "title_handle": title_handle_match.group(1) if title_handle_match else "",
                "found_as": "account_card",
                "card_link_url": card_link,
                "profile_url": card_link if card_platform else "",
            })

        # Address lines: profiles shown as ordinary results (no follower count).
        for match in ADDRESS_LINE_PATTERN.finditer(text):
            platform, handle_or_reason = profile_from_address(match.group("domain"), match.group("path").strip())
            if platform is None:
                if handle_or_reason:
                    skipped_address_lines.append((raw_path.name, match.group(0).strip(), handle_or_reason))
                    if "|" in handle_or_reason:  # post author: listed for the user's review
                        lines_above = [line.strip() for line in text[:match.start()].splitlines() if line.strip()]
                        lines_below = [line.strip() for line in text[match.end():].splitlines() if line.strip()]
                        author_platform = handle_or_reason.split(":")[0]
                        author_handle = handle_or_reason.split("|")[1]
                        post_authors.append({
                            "candidate_id": candidate_id, "platform": author_platform, "handle": author_handle,
                            "likely_profile_url": ADDRESS_PROFILE_URLS[author_platform].format(handle=author_handle),
                            "address_line": match.group(0).strip(),
                            "result_title": lines_above[-2] if len(lines_above) >= 2 else "",
                            "snippet": lines_below[0] if lines_below else "", "raw_file": raw_path.name})
                continue
            handle = handle_or_reason
            # The title is the result's first line: two non-blank lines up (title, site name, address).
            lines_above = [line.strip() for line in text[:match.start()].splitlines() if line.strip()]
            output_rows.append({
                "candidate_id": candidate_id, "raw_file": raw_path.name, "retrieved": read_header(text),
                "found_as": "address_line", "platform": platform, "account_label": handle,
                "count_shown": "", "count_floor": "", "count_unit": "",
                "handle_in_recorded_links": handle.lstrip("@").lower() in recorded_urls.get(candidate_id, ""),
                "title_line": lines_above[-2] if len(lines_above) >= 2 else "", "title_handle": "",
                "address_line": match.group(0).strip(),
                "profile_url": ADDRESS_PROFILE_URLS[platform].format(handle=handle),
            })

        # Links section: profile links become rows (dropped below if already listed); post links go to review.
        for url, link_text in links:
            platform, handle_or_reason = profile_from_url(url)
            if platform is None:
                if handle_or_reason and "|" in handle_or_reason:
                    author_platform = handle_or_reason.split(":")[0]
                    author_handle = handle_or_reason.split("|")[1]
                    post_authors.append({
                        "candidate_id": candidate_id, "platform": author_platform, "handle": author_handle,
                        "likely_profile_url": ADDRESS_PROFILE_URLS[author_platform].format(handle=author_handle),
                        "address_line": url, "result_title": link_text, "snippet": "", "raw_file": raw_path.name})
                continue
            output_rows.append({
                "candidate_id": candidate_id, "raw_file": raw_path.name, "retrieved": read_header(text),
                "found_as": "result_link", "platform": platform, "account_label": handle_or_reason,
                "count_shown": "", "count_floor": "", "count_unit": "",
                "handle_in_recorded_links": handle_or_reason.lstrip("@").lower() in recorded_urls.get(candidate_id, ""),
                "title_line": link_text, "title_handle": "", "address_line": "", "profile_url": url,
                "card_link_url": "",
            })

    # An address-line or result-link account already listed for the same candidate and platform (as a card's
    # label, title handle or card link, or an earlier row) is dropped, so each account shows once.
    seen, kept_rows, duplicate_address_rows = set(), [], 0
    for row in output_rows:  # cards first within each file, so a card wins over an address line
        handles = {row["account_label"].lstrip("@").lower(), row["title_handle"].lower()} - {""}
        if row.get("profile_url"):
            url_platform, url_handle = profile_from_url(row["profile_url"])
            if url_platform:
                handles.add(url_handle.lstrip("@").lower())
        keys = {(row["candidate_id"], row["platform"], handle) for handle in handles}
        if row["found_as"] in ("address_line", "result_link") and keys & seen:
            duplicate_address_rows += 1
            continue
        seen |= keys
        kept_rows.append(row)
    output_rows = kept_rows

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
    print(f"handle found in the candidate's recorded URLs: {sum(row['handle_in_recorded_links'] for row in output_rows)}")
    print(f"account boxes with their exact link: {sum(bool(row.get('card_link_url')) for row in output_rows)}; "
          f"profile rows from result links: {sum(row['found_as'] == 'result_link' for row in output_rows)}")
    address_rows = [row for row in output_rows if row["found_as"] == "address_line"]
    print(f"address-line profiles kept: {len(address_rows)}; dropped as already listed: {duplicate_address_rows}")
    for row in address_rows:
        print(f"   kept  {row['raw_file']}: {row['address_line']}")
    print(f"social address lines skipped: {len(skipped_address_lines)}")
    for file_name, line, reason in skipped_address_lines:
        print(f"   skip  {file_name}: {line}  ({reason.split('|')[0]})")
    update_post_authors_review(post_authors)
    print(f"wrote {OUTPUT_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
