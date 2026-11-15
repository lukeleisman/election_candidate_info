"""Probe: which ways of reading a follower count work today, per platform?

A one-off test (user, 2026-11-15), not part of `make all`. For a few known accounts per platform it
tries every method in METHODS below, one request at a time, and writes a raw table so the user can
see what each method actually returned. It draws no conclusions: it records the HTTP status, the
final URL (a redirect to a login page shows up there), the count text it found (if any) and a short
excerpt around it. Every response body is saved so any row can be checked by hand.

Run from the repo root:
    /opt/anaconda3/envs/election-candidate-info/bin/python scripts/social_counts/probe_follower_counts.py
Optional: YOUTUBE_API_KEY=... in the environment turns on the youtube_data_api method.

Output (gitignored, under data/raw/):
    data/raw/social_counts_probe/<run time>/probe_results.csv
    data/raw/social_counts_probe/<run time>/responses/<platform>__<method>__<handle>.txt
"""

import csv
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------------------------
# Settings (every judgment call is here)
# ---------------------------------------------------------------------------------------------

# Where the accounts to test come from: the recorded-links review file written by
# build_dashboard.py (every social link in candidate_links.csv, with a decision column).
RECORDED_LINKS_PATH = REPO_ROOT / "data" / "tables" / "social_recorded_links_added.csv"
# Google's account boxes (count_shown, e.g. "2.2K+"), read by extract_social_from_google.py.
# Shown next to each probe row for the same candidate + platform, so the two can be compared.
GOOGLE_ACCOUNTS_PATH = REPO_ROOT / "data" / "endorsements" / "social_accounts_google.csv"

OUTPUT_ROOT = REPO_ROOT / "data" / "raw" / "social_counts_probe"

# Which accounts to test. Per platform: ACCOUNTS_WITH_GOOGLE_COUNT accounts whose decision is
# "already in table" (so Google showed a count we can compare against) and ACCOUNTS_WITHOUT_GOOGLE_COUNT
# whose decision is "added" (recorded link, no count today). Drawn at random with a fixed seed so a
# rerun tests the same accounts.
ACCOUNTS_WITH_GOOGLE_COUNT = 2
ACCOUNTS_WITHOUT_GOOGLE_COUNT = 1
SAMPLE_SEED = 20261115
# Facebook share links (facebook.com/share/...) are left out of the sample: they are redirects, not
# a profile address, so they would test the redirect rather than the count.
SKIP_URL_PATTERNS = [r"facebook\.com/share/"]

# Politeness (same spirit as fetch_endorsement_pages.py): one request at a time, at least
# SECONDS_BETWEEN_REQUESTS between any two, and at least SECONDS_BETWEEN_SAME_HOST between two
# requests to the same host.
SECONDS_BETWEEN_REQUESTS = 3
SECONDS_BETWEEN_SAME_HOST = 32  # user, 2026-11-15
REQUEST_TIMEOUT_SECONDS = 30

# Same browser string as scripts/fetch_endorsement_pages.py (USER_AGENT there).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Instagram's own web app sends this app ID to its internal profile endpoint. It is not a key
# of ours; it is the public value baked into instagram.com's JavaScript (widely documented).
# OPEN QUESTION: the user decides whether an undocumented internal endpoint is acceptable to use.
INSTAGRAM_WEB_APP_ID = "936619743392459"

# Count text in page text, e.g. "1,234 Followers", "2.2K followers", "15.3K subscribers".
# Captures the number as written; parse_count_text() turns it into a number.
COUNT_TEXT_PATTERN = re.compile(r"(?P<count>\d[\d.,]*\s?[KkMm]?\+?)\s+(?P<unit>followers|subscribers)", re.IGNORECASE)
EXCERPT_CHARACTERS = 160

# The methods to try. Each entry: platform, method name, kind, and a note shown in the output.
#   kind "official_api"   documented, supported API
#   kind "public_page"    the public profile page as a logged-out visitor sees it
#   kind "unofficial"     an undocumented endpoint or a third-party service (see note)
METHODS = [
    {"platform": "Bluesky", "method": "bluesky_public_api", "kind": "official_api",
     "note": "public.api.bsky.app app.bsky.actor.getProfile; no login, no key"},
    {"platform": "YouTube", "method": "youtube_data_api", "kind": "official_api",
     "note": "YouTube Data API v3 channels.list part=statistics (1 quota unit); needs YOUTUBE_API_KEY"},
    {"platform": "YouTube", "method": "youtube_page", "kind": "public_page",
     "note": "channel page; 'N subscribers' in the page data"},
    {"platform": "TikTok", "method": "tiktok_page", "kind": "public_page",
     "note": "profile page; __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON, stats and statsV2 followerCount"},
    {"platform": "Instagram", "method": "instagram_page", "kind": "public_page",
     "note": "profile page; 'N Followers' in the meta description"},
    {"platform": "Instagram", "method": "instagram_web_profile_info", "kind": "unofficial",
     "note": "instagram.com's own internal endpoint (api/v1/users/web_profile_info), undocumented"},
    {"platform": "Threads", "method": "threads_page", "kind": "public_page",
     "note": "profile page; 'N Followers' in the meta description"},
    {"platform": "Facebook", "method": "facebook_page", "kind": "public_page",
     "note": "profile page as a logged-out visitor"},
    {"platform": "Facebook", "method": "facebook_page_plugin", "kind": "public_page",
     "note": "Facebook's embeddable Page Plugin (plugins/page.php), meant for websites"},
    {"platform": "X", "method": "x_syndication_followbutton", "kind": "unofficial",
     "note": "old follow-button feed cdn.syndication.twimg.com; undocumented, may be shut down"},
    {"platform": "X", "method": "x_fxtwitter_api", "kind": "unofficial",
     "note": "api.fxtwitter.com, a third-party service (sends the handle to them)"},
    {"platform": "X", "method": "x_page", "kind": "public_page",
     "note": "x.com profile page; expected to be drawn by script (no count in the HTML)"},
    {"platform": "LinkedIn", "method": "linkedin_page", "kind": "public_page",
     "note": "profile or company page as a logged-out visitor"},
]


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------

def handle_from_url(url):
    """The account part of a profile URL, case kept (account_key in the review file is lowercased).
    Examples: instagram.com/billfor1st/ -> billfor1st; tiktok.com/@x -> x; bsky.app/profile/a.b -> a.b;
    youtube.com/@x -> @x; youtube.com/channel/UC... -> channel/UC...; linkedin.com/in/x -> in/x."""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if not path_parts:
        return ""
    if path_parts[0] in ("profile",) and len(path_parts) > 1:  # Bluesky
        return path_parts[1]
    if path_parts[0] in ("in", "company", "channel", "c", "user") and len(path_parts) > 1:
        return f"{path_parts[0]}/{path_parts[1]}"  # LinkedIn and YouTube keep the prefix
    if "youtube.com" in url:
        return path_parts[0]  # "@handle" kept with the @
    return path_parts[0].lstrip("@")


def parse_count_text(count_text):
    """'2.2K+' -> 2200; '1,234' -> 1234; '15.3M' -> 15300000. None when it can't be read."""
    if count_text is None:
        return None
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


def find_count_in_text(text):
    """First 'N followers/subscribers' in the text: (count_text, excerpt) or (None, None)."""
    match = COUNT_TEXT_PATTERN.search(text or "")
    if not match:
        return None, None
    start = max(0, match.start() - EXCERPT_CHARACTERS // 2)
    excerpt = text[start:match.end() + EXCERPT_CHARACTERS // 2]
    return match.group("count").strip(), " ".join(excerpt.split())


def meta_description(html):
    """Contents of <meta name="description"> or <meta property="og:description">, joined."""
    found = re.findall(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]*)"', html or "")
    return " | ".join(found)


# ---------------------------------------------------------------------------------------------
# One function per method. Each returns a dict: request_url, plus (after the request) count_text,
# count_value, excerpt. The caller does the request so pacing lives in one place.
# ---------------------------------------------------------------------------------------------

def build_request(method, url, handle):
    """(request_url, extra_headers) for a method, or (None, reason) to skip."""
    if method == "bluesky_public_api":
        return f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={quote(handle)}", {}
    if method == "youtube_data_api":
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            return None, "skipped: YOUTUBE_API_KEY not set"
        if handle.startswith("channel/"):
            selector = f"id={quote(handle.split('/', 1)[1])}"
        elif handle.startswith("@"):
            selector = f"forHandle={quote(handle)}"
        else:
            return None, f"skipped: no handle or channel id in {url}"
        return f"https://www.googleapis.com/youtube/v3/channels?part=statistics&{selector}&key={api_key}", {}
    if method == "instagram_web_profile_info":
        return (f"https://i.instagram.com/api/v1/users/web_profile_info/?username={quote(handle)}",
                {"X-IG-App-ID": INSTAGRAM_WEB_APP_ID})
    if method == "facebook_page_plugin":
        return f"https://www.facebook.com/plugins/page.php?href={quote(url, safe='')}&tabs=&width=340&height=130", {}
    if method == "x_syndication_followbutton":
        return f"https://cdn.syndication.twimg.com/widgets/followbutton/info.json?screen_names={quote(handle)}", {}
    if method == "x_fxtwitter_api":
        return f"https://api.fxtwitter.com/{quote(handle)}", {}
    if method == "x_page":
        return f"https://x.com/{quote(handle)}", {}
    # Public pages: the recorded URL as it is.
    return url, {}


def read_count(method, body):
    """(count_text, excerpt) from a response body, per method. Never guesses: None when not found."""
    if method == "bluesky_public_api":
        try:
            data = json.loads(body)
        except ValueError:
            return None, None
        if "followersCount" in data:
            return str(data["followersCount"]), f"followersCount={data['followersCount']} handle={data.get('handle')}"
        return None, None
    if method == "youtube_data_api":
        try:
            items = json.loads(body).get("items") or []
        except ValueError:
            return None, None
        if items and "subscriberCount" in items[0].get("statistics", {}):
            statistics = items[0]["statistics"]
            return statistics["subscriberCount"], json.dumps(statistics)
        return None, None
    if method == "tiktok_page":
        match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', body, re.S)
        if not match:
            return None, None
        try:
            user_detail = json.loads(match.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]
            stats = user_detail["userInfo"]["stats"]
        except (ValueError, KeyError, TypeError):
            return None, "rehydration JSON present, no userInfo.stats"
        stats_v2 = user_detail["userInfo"].get("statsV2", {})
        # statsV2 is reported to hold the exact count, stats a rounded one; both shown.
        count_text = str(stats_v2.get("followerCount", stats.get("followerCount")))
        return count_text, f"stats.followerCount={stats.get('followerCount')} statsV2.followerCount={stats_v2.get('followerCount')}"
    if method == "instagram_web_profile_info":
        try:
            user = json.loads(body)["data"]["user"]
            return str(user["edge_followed_by"]["count"]), f"edge_followed_by.count={user['edge_followed_by']['count']} username={user.get('username')}"
        except (ValueError, KeyError, TypeError):
            return None, None
    if method == "x_syndication_followbutton":
        try:
            data = json.loads(body)
        except ValueError:
            return None, None
        if data and isinstance(data, list) and "followers_count" in data[0]:
            return str(data[0]["followers_count"]), json.dumps(data[0])[:EXCERPT_CHARACTERS]
        return None, None
    if method == "x_fxtwitter_api":
        try:
            user = json.loads(body)["user"]
            return str(user["followers"]), f"followers={user['followers']} screen_name={user.get('screen_name')}"
        except (ValueError, KeyError, TypeError):
            return None, None
    # Public pages: the meta description first (short, made for previews), then the whole HTML.
    count_text, excerpt = find_count_in_text(meta_description(body))
    if count_text:
        return count_text, "meta: " + excerpt
    count_text, excerpt = find_count_in_text(body)
    if count_text:
        return count_text, "page: " + excerpt
    return None, None


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

def pick_accounts():
    """The accounts to test, per platform (see ACCOUNTS_* settings)."""
    links = pd.read_csv(RECORDED_LINKS_PATH, dtype=str)
    for pattern in SKIP_URL_PATTERNS:
        links = links[~links["url"].str.contains(pattern, regex=True)]
    platforms = sorted({entry["platform"] for entry in METHODS})
    random_generator = random.Random(SAMPLE_SEED)
    chosen = []
    for platform in platforms:
        for decision, how_many in (("already in table", ACCOUNTS_WITH_GOOGLE_COUNT),
                                   ("added", ACCOUNTS_WITHOUT_GOOGLE_COUNT)):
            pool = links[(links["platform"] == platform) & (links["decision"] == decision)]
            rows = pool.to_dict("records")
            random_generator.shuffle(rows)
            chosen.extend(rows[:how_many])
    return chosen


def google_counts_for(google_accounts, candidate_id, platform):
    """Google's counts shown for this candidate + platform, as 'label: count' (raw, for comparison)."""
    rows = google_accounts[(google_accounts["candidate_id"] == candidate_id)
                           & (google_accounts["platform"] == platform)
                           & google_accounts["count_shown"].notna()]
    return "; ".join(f"{row.account_label}: {row.count_shown}" for row in rows.itertuples())


def main():
    run_time = datetime.now().astimezone()
    run_folder = OUTPUT_ROOT / run_time.strftime("%Y-%m-%dT%H%M%S")
    responses_folder = run_folder / "responses"
    responses_folder.mkdir(parents=True, exist_ok=True)

    google_accounts = pd.read_csv(GOOGLE_ACCOUNTS_PATH, dtype=str)
    accounts = pick_accounts()

    # Every (account, method) pair for the account's platform.
    jobs = []
    for account in accounts:
        handle = handle_from_url(account["url"])
        for entry in METHODS:
            if entry["platform"] == account["platform"]:
                jobs.append({"account": account, "handle": handle, **entry})
    # Take one job from each platform in turn, so the same-host wait overlaps with other
    # platforms' requests (order only; changes no result).
    jobs_by_platform = {}
    for job in jobs:
        jobs_by_platform.setdefault(job["platform"], []).append(job)
    jobs = []
    while any(jobs_by_platform.values()):
        for platform_jobs in jobs_by_platform.values():
            if platform_jobs:
                jobs.append(platform_jobs.pop(0))

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    last_request_time = 0.0
    last_request_by_host = {}
    results = []
    print(f"{len(accounts)} accounts, {len(jobs)} requests; writing to {run_folder}")

    for job_number, job in enumerate(jobs, start=1):
        account, method = job["account"], job["method"]
        request_url, extra_headers = build_request(method, account["url"], job["handle"])
        result = {
            "candidate_id": account["candidate_id"], "platform": job["platform"], "url": account["url"],
            "handle": job["handle"], "decision_in_review_file": account["decision"],
            "google_counts_same_candidate_platform": google_counts_for(google_accounts, account["candidate_id"], job["platform"]),
            "method": method, "method_kind": job["kind"], "method_note": job["note"],
            "request_url": "", "http_status": "", "final_url": "", "response_characters": "",
            "count_text": "", "count_value": "", "excerpt": "", "error": "", "response_file": "",
            "requested_at": "",
        }
        if request_url is None:
            result["error"] = extra_headers  # the skip reason
            results.append(result)
            print(f"[{job_number}/{len(jobs)}] {method} {job['handle']}: {extra_headers}")
            continue
        # Never print or save the API key.
        result["request_url"] = re.sub(r"key=[^&]+", "key=REDACTED", request_url)

        # Pacing: overall gap, then same-host gap.
        host = urlparse(request_url).netloc
        wait_seconds = max(SECONDS_BETWEEN_REQUESTS - (time.time() - last_request_time),
                           SECONDS_BETWEEN_SAME_HOST - (time.time() - last_request_by_host.get(host, 0)), 0)
        time.sleep(wait_seconds)

        result["requested_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            response = session.get(request_url, headers=extra_headers, timeout=REQUEST_TIMEOUT_SECONDS)
            body = response.text
            result["http_status"] = response.status_code
            result["final_url"] = response.url if response.url != request_url else ""
            result["response_characters"] = len(body)
            count_text, excerpt = read_count(method, body)
            result["count_text"] = count_text or ""
            result["count_value"] = parse_count_text(count_text) if count_text else ""
            result["excerpt"] = excerpt or ""
            safe_handle = re.sub(r"[^A-Za-z0-9._@-]+", "_", job["handle"])
            response_file = responses_folder / f"{job['platform']}__{method}__{safe_handle}.txt"
            response_file.write_text(body, encoding="utf-8")
            result["response_file"] = str(response_file.relative_to(REPO_ROOT))
        except requests.RequestException as error:
            result["error"] = f"{type(error).__name__}: {error}"
        finally:
            last_request_time = time.time()
            last_request_by_host[host] = last_request_time

        results.append(result)
        print(f"[{job_number}/{len(jobs)}] {method} {job['handle']}: status {result['http_status']}, "
              f"count {result['count_text'] or '-'} {result['error']}")

    results_path = run_folder / "probe_results.csv"
    with open(results_path, "w", newline="", encoding="utf-8") as results_file:
        writer = csv.DictWriter(results_file, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"Wrote {results_path}")


if __name__ == "__main__":
    main()
