"""Fetch follower counts for recorded social links, one polite request at a time.

Methods chosen from the 2026-11-15 probe (scripts/social_counts/probe_follower_counts.py; raw results in
data/raw/social_counts_probe/) and the user's decisions that day:
    Bluesky   public API app.bsky.actor.getProfiles (no login, no key)        exact
    TikTok    profile page, __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON            exact
    X         x.com profile page, header data "followers:N,following:M"       exact   (user: x.com, not fxtwitter)
    Facebook  Page Plugin (plugins/page.php), "followerCountFormatted"        rounded ("9.5K")
    YouTube   channel page, "N subscribers"                                    as shown (user: page, no API key)
Instagram, Threads and LinkedIn had no working method: they go straight to the review list, as does every
link whose fetch found no count.

Which links: the rows of data/tables/social_recorded_links_added.csv (written by build_dashboard.py) whose
decision is in LINK_DECISIONS_TO_FETCH, i.e. every social profile link in candidate_links.csv. Not
re-derived here.

Outputs (public, committed):
    data/social_counts/follower_counts_history.csv   one row per link per run, appended (keeps growth over time)
    data/social_counts/follower_counts_review.csv    rewritten each run: links with no count from this run, and why
Raw (gitignored): data/raw/follower_counts/<run time>/<platform>/<handle>.txt (each response body)

Run from the repo root (make follower-counts):
    python scripts/social_counts/fetch_follower_counts.py                      # every platform
    python scripts/social_counts/fetch_follower_counts.py --platforms X,Bluesky --limit 2   # quick test
    python scripts/social_counts/fetch_follower_counts.py --reuse-raw-folder data/raw/follower_counts/<run time>
        # pick up a stopped run: links whose page is already saved in that folder are read from the saved page,
        # the rest are requested (Bluesky is always requested again: one call)
Each row is appended to the history file as soon as it is done (since 2026-11-15), so a stopped run keeps its rows.
"""

import argparse
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------------------------
# Settings (every judgment call is here)
# ---------------------------------------------------------------------------------------------

RECORDED_LINKS_PATH = REPO_ROOT / "data" / "tables" / "social_recorded_links_added.csv"
# "added" = recorded link not in Google's account boxes; "already in table" = also shown by Google.
# User 2026-11-15: show both counts (Google's and ours), so both kinds are fetched.
LINK_DECISIONS_TO_FETCH = ["added", "already in table"]

OUTPUT_FOLDER = REPO_ROOT / "data" / "social_counts"
HISTORY_PATH = OUTPUT_FOLDER / "follower_counts_history.csv"
REVIEW_PATH = OUTPUT_FOLDER / "follower_counts_review.csv"
RAW_ROOT = REPO_ROOT / "data" / "raw" / "follower_counts"

# Politeness (user, 2026-11-15): one request at a time, 3 s between any two, 32 s between two requests to the
# same host. Platforms are interleaved so the 32 s waits overlap.
SECONDS_BETWEEN_REQUESTS = 3
SECONDS_BETWEEN_SAME_HOST = 32
REQUEST_TIMEOUT_SECONDS = 30
# Stop asking a platform after this many failures in a row (an error status, or a page with no count:
# TikTok and X answer a block with an ordinary-looking page). The rest of that platform's links are written
# as "not tried: platform stopped" and go to the review list.
MAX_CONSECUTIVE_FAILURES_PER_PLATFORM = 3
# Which platforms count "no count found on the page" as a failure for the stop rule above. TikTok and X answer a
# block with an ordinary page, so there it may mean a block. On Facebook and YouTube it means the page has no count
# (e.g. a personal profile, not a Page): first run 2026-11-15 stopped Facebook after 3 of those, wrongly.
NO_COUNT_IS_FAILURE_PLATFORMS = ["TikTok", "X"]

# Same browser string as scripts/fetch_endorsement_pages.py (USER_AGENT there).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Platform -> method. A platform not listed has no method (review list, nothing fetched).
METHOD_BY_PLATFORM = {
    "Bluesky": "bluesky_api",
    "TikTok": "tiktok_page",
    "X": "x_page",
    "Facebook": "facebook_page_plugin",
    "YouTube": "youtube_page",
}
# Bluesky's getProfiles takes up to 25 accounts per call (third-party docs; Bluesky publishes no number).
# It can return fewer than asked with no error, so each missing account is written as "not returned".
BLUESKY_ACCOUNTS_PER_CALL = 25
# A Bluesky handle is a domain name (name.bsky.social, or a custom domain) or a DID (did:plc:...). One handle
# without a dot (bsky.app/profile/omarifor35, ALD-35-003) made the API reject the whole batch on 2026-11-15.
# Handles that don't match go to the review list unrequested; the right handle is not guessed.
BLUESKY_HANDLE_PATTERN = re.compile(r"^(did:[a-z]+:[A-Za-z0-9._:%-]+|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+)$")

# Links the methods can't read, sent to the review list without a request.
#   Facebook share links (facebook.com/share/...) are redirects to an unknown page, not a profile address.
SKIP_URL_RULES = [
    (r"facebook\.com/share/", "Facebook share link: open by hand to find the page"),
]

# Count precision. "rounded" when the count text ends in K or M ("9.5K", "1.2M"), else "exact" (TikTok,
# Bluesky and X give whole numbers; Facebook and YouTube give whole numbers below 1,000).
ROUNDED_COUNT_PATTERN = re.compile(r"[KkMm]\+?$")

# X: the profile header object on x.com holds "followers:N,following:M,hasHighlights". The probe found exactly
# one per page (7 pages); other "followers" numbers on the page belong to other accounts shown there.
X_HEADER_PATTERN = re.compile(r"followers:(\d+),following:(\d+),hasHighlights")
# YouTube: the channel header's metadata text, e.g. {"content":"14 subscribers"}.
YOUTUBE_SUBSCRIBERS_PATTERN = re.compile(r'"content":"([\d.,]+\s?[KkMm]?) subscribers?"')
# Facebook Page Plugin data fields kept so a reader can check it is the right page (e.g. Dowell's link is the
# "Campaign page for Ald. Pat Dowell", while Google's box was another page).
FACEBOOK_PLUGIN_FIELDS = ["followerCountFormatted", "pageName", "pageCategory", "pageDescription"]
# The plugin's second form (seen 2026-11-15, e.g. Alderman Brian Hopkins): no hidden fields, the page shows
# "<Page name> 4,199 followers Follow Page" as visible text. Read when followerCountFormatted is missing.
FACEBOOK_VISIBLE_COUNT_PATTERN = re.compile(r"^Facebook (?P<name>.*?) (?P<count>\d[\d,.]*\s?[KkMm]?) followers\b")
DETAIL_CHARACTERS = 200


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------

def handle_from_url(url):
    """Account part of a profile URL, case kept. Same rules as probe_follower_counts.handle_from_url:
    twitter.com/#!/name -> name; tiktok.com/@x -> x; bsky.app/profile/a.b -> a.b; youtube.com/@x -> @x;
    youtube.com/channel/UC... -> channel/UC...; facebook.com/Name -> Name."""
    parsed = urlparse(url)
    path = parsed.fragment[1:] if parsed.fragment.startswith("!/") else parsed.path
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    if parts[0] == "profile" and len(parts) > 1:
        return parts[1]
    # Facebook page forms (fixed 2026-11-15: the first run used "p" as the handle, so two such links for one
    # candidate shared a raw file name): /p/<Name-number>/ -> Name-number; /people/<Name>/<number>/ -> number;
    # profile.php?id=<number> -> number.
    if "facebook.com" in parsed.netloc:
        if parts[0] == "p" and len(parts) > 1:
            return parts[1]
        if parts[0] == "people" and len(parts) > 2:
            return parts[2]
        if parts[0] == "profile.php":
            query_id = re.search(r"(?:^|&)id=(\d+)", parsed.query)
            return query_id.group(1) if query_id else "profile.php"
    if parts[0] in ("in", "company", "channel", "c", "user") and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    if "youtube.com" in parsed.netloc:
        return parts[0]
    return parts[0].lstrip("@")


def parse_count_text(count_text):
    """'2.2K' -> 2200; '1,234' -> 1234; '15.3M' -> 15300000; None when unreadable."""
    cleaned = str(count_text).replace(",", "").replace("+", "").strip()
    multiplier = 1
    if cleaned[-1:].lower() == "k":
        multiplier, cleaned = 1_000, cleaned[:-1]
    elif cleaned[-1:].lower() == "m":
        multiplier, cleaned = 1_000_000, cleaned[:-1]
    try:
        return int(round(float(cleaned) * multiplier))
    except ValueError:
        return None


def precision_of(count_text):
    return "rounded" if ROUNDED_COUNT_PATTERN.search(str(count_text).strip()) else "exact"


def visible_text(html):
    """Page text a visitor sees (scripts and styles removed), spaces collapsed."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def request_url_for(method, url, handle):
    """The address to request for one link (Bluesky is batched separately)."""
    if method == "x_page":
        return f"https://x.com/{quote(handle)}"
    if method == "facebook_page_plugin":
        return f"https://www.facebook.com/plugins/page.php?href={quote(url, safe='')}&tabs=&width=340&height=130"
    if method == "tiktok_page":
        return f"https://www.tiktok.com/@{quote(handle)}"
    return url  # youtube_page: the recorded channel address


def read_count(method, body):
    """(count_text, detail) from one response body; (None, detail-or-None) when no count is found."""
    if method == "x_page":
        headers = X_HEADER_PATTERN.findall(body)
        if len(headers) == 1:
            return headers[0][0], f"followers:{headers[0][0]},following:{headers[0][1]}"
        if len(headers) > 1:  # never seen in the probe; not guessed between them
            return None, f"{len(headers)} profile headers found: " + "; ".join(h[0] for h in headers)
        return None, None
    if method == "tiktok_page":
        match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', body, re.S)
        if not match:
            return None, "no rehydration JSON (possible block page)"
        try:
            user_info = json.loads(match.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        except (ValueError, KeyError, TypeError):
            return None, "rehydration JSON without userInfo (possible block page or no such account)"
        stats, stats_v2 = user_info.get("stats", {}), user_info.get("statsV2", {})
        # statsV2 is reported to hold the exact count where stats may be rounded; both kept in the detail.
        count = stats_v2.get("followerCount", stats.get("followerCount"))
        detail = f"stats.followerCount={stats.get('followerCount')} statsV2.followerCount={stats_v2.get('followerCount')}"
        return (str(count) if count is not None else None), detail
    if method == "facebook_page_plugin":
        found = {}
        for field in FACEBOOK_PLUGIN_FIELDS:
            field_match = re.search(rf'"{field}":"((?:[^"\\]|\\.)*)"', body)
            if field_match:
                found[field] = json.loads(f'"{field_match.group(1)}"')  # undo \n, \/ escapes
        detail = "; ".join(f"{key}={' '.join(value.split())}" for key, value in found.items())[:DETAIL_CHARACTERS]
        if found.get("followerCountFormatted"):
            return found["followerCountFormatted"], detail
        visible = visible_text(body)
        visible_match = FACEBOOK_VISIBLE_COUNT_PATTERN.match(visible)
        if visible_match:
            return visible_match.group("count"), f"visible text: {visible[:DETAIL_CHARACTERS]}"
        return None, f"visible text: {visible[:DETAIL_CHARACTERS]}"
    if method == "youtube_page":
        match = YOUTUBE_SUBSCRIBERS_PATTERN.search(body)
        return (match.group(1), f"{match.group(1)} subscribers") if match else (None, None)
    raise ValueError(f"unknown method {method}")


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

class PoliteSession:
    """requests.Session with the pacing rules above."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self.last_request_time = 0.0
        self.last_request_by_host = {}

    def get(self, url):
        host = urlparse(url).netloc
        wait_seconds = max(SECONDS_BETWEEN_REQUESTS - (time.time() - self.last_request_time),
                           SECONDS_BETWEEN_SAME_HOST - (time.time() - self.last_request_by_host.get(host, 0)), 0)
        time.sleep(wait_seconds)
        try:
            return self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        finally:
            self.last_request_time = self.last_request_by_host[host] = time.time()


def blank_result(link, run_time):
    return {
        "fetched_at": run_time, "candidate_id": link["candidate_id"], "platform": link["platform"],
        "url": link["url"], "handle": handle_from_url(link["url"]), "method": METHOD_BY_PLATFORM.get(link["platform"], ""),
        "status": "", "count_value": "", "count_text": "", "count_precision": "", "http_status": "",
        "detail": "", "raw_file": "",
    }


def save_raw(raw_folder, result, body):
    safe_handle = re.sub(r"[^A-Za-z0-9._@-]+", "_", result["handle"] or "no_handle")
    raw_file = raw_folder / result["platform"] / f"{result['candidate_id']}__{safe_handle}.txt"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(body, encoding="utf-8")
    return str(raw_file.relative_to(REPO_ROOT))


HISTORY_COLUMNS = ["fetched_at", "candidate_id", "platform", "url", "handle", "method", "status", "count_value",
                   "count_text", "count_precision", "http_status", "detail", "raw_file"]


def append_history(rows):
    """Append rows to HISTORY_PATH right away (header written once), so a stopped run keeps what it fetched."""
    if not rows:
        return
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    write_header = not HISTORY_PATH.exists()
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as history_file:
        writer = csv.DictWriter(history_file, fieldnames=HISTORY_COLUMNS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def saved_raw_file(reuse_folder, result):
    """The page an earlier run saved for this link (same name rule as save_raw), or None."""
    safe_handle = re.sub(r"[^A-Za-z0-9._@-]+", "_", result["handle"] or "no_handle")
    candidate_file = reuse_folder / result["platform"] / f"{result['candidate_id']}__{safe_handle}.txt"
    return candidate_file if candidate_file.exists() else None


def fill_count(result, count_text):
    result["count_text"] = count_text
    result["count_value"] = parse_count_text(count_text)
    result["count_precision"] = precision_of(count_text)
    result["status"] = "ok" if result["count_value"] is not None else "count unreadable"


def fetch_bluesky(links, polite, run_time, raw_folder):
    """Bluesky in batches of BLUESKY_ACCOUNTS_PER_CALL."""
    results = []
    valid_links = []
    for link in links:
        result = blank_result(link, run_time)
        if BLUESKY_HANDLE_PATTERN.match(result["handle"]):
            valid_links.append(link)
        else:
            result["status"] = "not a valid Bluesky handle (needs a domain, e.g. name.bsky.social)"
            results.append(result)
    links = valid_links
    for start in range(0, len(links), BLUESKY_ACCOUNTS_PER_CALL):
        batch = [blank_result(link, run_time) for link in links[start:start + BLUESKY_ACCOUNTS_PER_CALL]]
        query = "&".join(f"actors={quote(result['handle'])}" for result in batch)
        try:
            response = polite.get(f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles?{query}")
            profiles = {profile["handle"].lower(): profile for profile in response.json().get("profiles", [])}
            raw_file = save_raw(raw_folder, {**batch[0], "handle": f"batch_{start}"}, response.text)
            for result in batch:
                result["http_status"], result["raw_file"] = response.status_code, raw_file
                profile = profiles.get(result["handle"].lower())
                if profile and "followersCount" in profile:
                    fill_count(result, str(profile["followersCount"]))
                    result["detail"] = f"displayName={profile.get('displayName', '')}"[:DETAIL_CHARACTERS]
                else:
                    result["status"] = "not returned (account not found, or left out of the reply)"
        except (requests.RequestException, ValueError) as error:
            for result in batch:
                result["status"], result["detail"] = "request failed", f"{type(error).__name__}: {error}"[:DETAIL_CHARACTERS]
        results.extend(batch)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platforms", help="comma-separated platforms to fetch (default: all with a method)")
    parser.add_argument("--limit", type=int, help="at most this many links per platform (for a quick test)")
    parser.add_argument("--reuse-raw-folder", help="read pages already saved in this raw folder instead of requesting them")
    arguments = parser.parse_args()

    run_started = datetime.now().astimezone()
    run_time = run_started.isoformat(timespec="seconds")
    raw_folder = RAW_ROOT / run_started.strftime("%Y-%m-%dT%H%M%S")

    links = pd.read_csv(RECORDED_LINKS_PATH, dtype=str).fillna("")
    links = links[links["decision"].isin(LINK_DECISIONS_TO_FETCH)]
    if arguments.platforms:
        links = links[links["platform"].isin(arguments.platforms.split(","))]
    links = links.drop_duplicates(["candidate_id", "url"])

    results, to_fetch = [], {}
    for link in links.to_dict("records"):
        if arguments.limit and len(to_fetch.get(link["platform"], [])) >= arguments.limit:
            continue
        skip_reason = next((reason for pattern, reason in SKIP_URL_RULES if re.search(pattern, link["url"])), None)
        if link["platform"] not in METHOD_BY_PLATFORM:
            result = blank_result(link, run_time)
            result["status"] = "no method for this platform"
            results.append(result)
        elif skip_reason:
            result = blank_result(link, run_time)
            result["status"], result["detail"] = "skipped", skip_reason
            results.append(result)
        else:
            to_fetch.setdefault(link["platform"], []).append(link)

    # Rows with no request (no method / skipped) are written now.
    append_history(results)
    reuse_folder = Path(arguments.reuse_raw_folder).resolve() if arguments.reuse_raw_folder else None
    reuse_run_time = (datetime.strptime(reuse_folder.name, "%Y-%m-%dT%H%M%S").astimezone().isoformat(timespec="seconds")
                      if reuse_folder else "")

    polite = PoliteSession()
    if "Bluesky" in to_fetch:
        bluesky_results = fetch_bluesky(to_fetch.pop("Bluesky"), polite, run_time, raw_folder)
        results.extend(bluesky_results)
        append_history(bluesky_results)

    # Other platforms: one request per link, taking one link from each platform in turn.
    queues = {platform: list(platform_links) for platform, platform_links in to_fetch.items()}
    consecutive_failures = {platform: 0 for platform in queues}
    total = sum(len(queue) for queue in queues.values())
    done = 0
    print(f"{total} page requests across {', '.join(queues)}; raw files in {raw_folder}")
    while any(queues.values()):
        for platform, queue in queues.items():
            if not queue:
                continue
            link = queue.pop(0)
            result = blank_result(link, run_time)
            done += 1
            if consecutive_failures[platform] >= MAX_CONSECUTIVE_FAILURES_PER_PLATFORM:
                result["status"] = f"not tried: platform stopped after {MAX_CONSECUTIVE_FAILURES_PER_PLATFORM} failures in a row"
                results.append(result)
                append_history([result])
                continue
            saved_page = saved_raw_file(reuse_folder, result) if reuse_folder else None
            try:
                if saved_page is not None:
                    # Saved by an earlier, stopped run. Its HTTP status was not saved, so it is left blank;
                    # fetched_at is the earlier run's time (the folder name).
                    body, status_code = saved_page.read_text(encoding="utf-8"), None
                    result["fetched_at"] = reuse_run_time
                    result["raw_file"] = str(saved_page.relative_to(REPO_ROOT))
                else:
                    response = polite.get(request_url_for(result["method"], link["url"], result["handle"]))
                    body, status_code = response.text, response.status_code
                    result["http_status"] = status_code
                    result["raw_file"] = save_raw(raw_folder, result, body)
                count_text, detail = read_count(result["method"], body)
                result["detail"] = detail or ""
                if status_code not in (200, None):
                    result["status"] = "error status"
                elif count_text:
                    fill_count(result, count_text)
                else:
                    result["status"] = "no count found on the page"
            except requests.RequestException as error:
                result["status"], result["detail"] = "request failed", f"{type(error).__name__}: {error}"[:DETAIL_CHARACTERS]
            if saved_page is None:  # a saved page says nothing about whether the platform is blocking now
                is_failure = result["status"] != "ok" and (
                    result["status"] != "no count found on the page" or platform in NO_COUNT_IS_FAILURE_PLATFORMS)
                consecutive_failures[platform] = consecutive_failures[platform] + 1 if is_failure else 0
            results.append(result)
            append_history([result])
            source = " (saved page)" if saved_page is not None else ""
            print(f"[{done}/{total}] {platform} {result['handle']}: {result['status']} {result['count_text']}{source}")

    # Review list: every link whose LATEST row in the history (any run) has no count, so a run of a few platforms
    # keeps the other platforms' open items.
    history = pd.read_csv(HISTORY_PATH, dtype=str, keep_default_na=False)
    latest = history.sort_values("fetched_at", kind="stable").drop_duplicates(["candidate_id", "url"], keep="last")
    review = latest[latest["status"] != "ok"].sort_values(["platform", "candidate_id"])
    review.to_csv(REVIEW_PATH, index=False, lineterminator="\n")
    review_rows = review

    status_counts = pd.Series([f"{r['platform']}: {r['status']}" for r in results]).value_counts()
    print(status_counts.to_string())
    print(f"Appended {len(results)} rows to {HISTORY_PATH.relative_to(REPO_ROOT)}; "
          f"{len(review_rows)} rows in {REVIEW_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
