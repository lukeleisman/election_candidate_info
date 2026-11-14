"""Snapshot every approved endorsement page in config/endorsement_sources.csv (PLAN.md §4).

For each registry row with fetch_approved == "yes" and a URL, send ONE GET request, one at a time,
and save under data/raw/endorsements/ (gitignored):
  <source_id>/<UTC timestamp>.<html|pdf|bin>   the response body, verbatim
  <source_id>/<UTC timestamp>.txt              visible text pulled from HTML (for reading and parsers)
Every request (including failures) is appended to data/raw/endorsements/manifest.json, and this run's
per-source result is written to data/raw/endorsements/last_run.csv, which says which pages CHANGED
since the previous successful snapshot. Changed pages are the ones to read for new endorsements.

Access policy (user, 2026-11-05 and 2026-11-13): no terms/robots checks; one fetch per site per run is
approved for every registry row with a URL; ask before adding many pages on one site.

Usage (from the repo root):
  python scripts/fetch_endorsement_pages.py              fetch every approved row
  python scripts/fetch_endorsement_pages.py --list       show what would be fetched; send nothing
  python scripts/fetch_endorsement_pages.py --only ID1,ID2   fetch just these source_ids
"""

import csv
import hashlib
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration: every judgment call lives here.
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO / "config" / "endorsement_sources.csv"
OUTPUT_DIR = REPO / "data" / "raw" / "endorsements"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
LAST_RUN_PATH = OUTPUT_DIR / "last_run.csv"

# Which registry rows to fetch: fetch_approved must equal this (user fills the column).
APPROVED_VALUE = "yes"

# User, 2026-11-13: use the repo's browser string (the same as scripts/fetch_cboe.py). An honest
# label was the other option; CTU returned 403 to one on 2026-11-04.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Politeness. Requests are always sequential. Between any two requests wait at least
# SECONDS_BETWEEN_REQUESTS; two requests to the same host (e.g. the two Sierra Club rows)
# wait at least SECONDS_BETWEEN_SAME_HOST.
SECONDS_BETWEEN_REQUESTS = 3
SECONDS_BETWEEN_SAME_HOST = 30
REQUEST_TIMEOUT_SECONDS = 45

# How "changed since last time" is decided. Raw HTML often changes on every load (tokens, timestamps),
# so the comparison uses the sha256 of the visible text by default.
# Options: "visible_text" (default) | "raw_bytes"
CHANGE_DETECTION = "visible_text"

# Keep a new snapshot file even when nothing changed? False = only the manifest row is written,
# pointing at the earlier identical file (saves disk; nothing is lost because the content is identical).
SAVE_UNCHANGED_SNAPSHOTS = False

# A page that loads (HTTP 200) but has less visible text than this is probably a bot wall or drawn by
# script (Sierra Club returned 200 with 0 characters on 2026-11-14). Such rows get try_chrome = yes in
# last_run.csv, as do HTTP errors and failed requests.
THIN_TEXT_CHARS = 300

# Tags whose text is not "visible" page text.
NON_VISIBLE_TAGS = ["script", "style", "noscript", "template", "svg"]

LAST_RUN_COLUMNS = ["source_id", "org_name", "url", "result", "http_status", "changed",
                    "try_chrome", "snapshot_file", "text_file", "text_chars", "error"]


def utc_now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest():
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return []


def save_manifest(records):
    MANIFEST_PATH.write_text(json.dumps(records, indent=2) + "\n")


def approved_rows():
    with open(REGISTRY_PATH, newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row["fetch_approved"].strip() == APPROVED_VALUE and row["url"].strip()]


def extension_for(content_type):
    """File extension from the Content-Type header."""
    content_type = (content_type or "").lower()
    if "html" in content_type:
        return "html"
    if "pdf" in content_type:
        return "pdf"
    if "json" in content_type:
        return "json"
    if "text/plain" in content_type:
        return "txt_raw"
    return "bin"


def visible_text(html_bytes):
    """Page text a reader would see: non-visible tags dropped, one line per text block, blanks removed."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(NON_VISIBLE_TAGS):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def last_good_record(manifest, source_id):
    """Most recent successful manifest record for this source (None if never fetched)."""
    for record in reversed(manifest):
        if record["source_id"] == source_id and record.get("result") == "ok":
            return record
    return None


def wait_politely(host, last_request_time, last_request_by_host):
    """Sleep until both spacing rules allow the next request."""
    now = time.monotonic()
    ready_at = last_request_time + SECONDS_BETWEEN_REQUESTS
    if host in last_request_by_host:
        ready_at = max(ready_at, last_request_by_host[host] + SECONDS_BETWEEN_SAME_HOST)
    if ready_at > now:
        time.sleep(ready_at - now)


def fetch_one(session, row, manifest):
    """Fetch one registry row; return (manifest record, last_run row)."""
    source_id, url = row["source_id"], row["url"].strip()
    retrieved_at = utc_now_text()
    record = {"source_id": source_id, "url": url, "retrieved_at": retrieved_at}
    run_row = {"source_id": source_id, "org_name": row["org_name"], "url": url}
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException as error:
        record.update(result="error", error=str(error)[:300])
        run_row.update(result="error", error=str(error)[:300], try_chrome="yes")
        return record, run_row

    body = response.content
    extension = extension_for(response.headers.get("Content-Type"))
    text = visible_text(body) if extension == "html" else ""
    raw_sha = hashlib.sha256(body).hexdigest()
    text_sha = hashlib.sha256(text.encode()).hexdigest() if text else ""
    record.update(final_url=response.url, http_status=response.status_code,
                  content_type=response.headers.get("Content-Type", ""), bytes=len(body),
                  sha256=raw_sha, text_sha256=text_sha, text_chars=len(text))
    run_row.update(http_status=response.status_code, text_chars=len(text))

    if response.status_code != 200:
        # Error pages are still saved: they show what the site sent back (e.g. a bot wall).
        record["result"] = "http_error"
        run_row["result"] = "http_error"
    else:
        record["result"] = "ok"
        run_row["result"] = "ok"

    previous = last_good_record(manifest, source_id)
    compare_key = "text_sha256" if CHANGE_DETECTION == "visible_text" and text_sha else "sha256"
    if record["result"] != "ok":
        changed = ""
    elif previous is None:
        changed = "first"
    else:
        changed = "yes" if previous.get(compare_key) != record[compare_key] else "no"
    record["changed"] = changed
    run_row["changed"] = changed

    if changed == "no" and not SAVE_UNCHANGED_SNAPSHOTS:
        record["snapshot_file"] = previous.get("snapshot_file", "")
        record["text_file"] = previous.get("text_file", "")
    else:
        source_dir = OUTPUT_DIR / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        stamp = retrieved_at.replace(":", "").replace("-", "")
        snapshot_path = source_dir / f"{stamp}.{extension}"
        snapshot_path.write_bytes(body)
        record["snapshot_file"] = str(snapshot_path.relative_to(REPO))
        if text:
            text_path = source_dir / f"{stamp}.txt"
            text_path.write_text(text + "\n")
            record["text_file"] = str(text_path.relative_to(REPO))
        else:
            record["text_file"] = ""
    thin = extension == "html" and len(text) < THIN_TEXT_CHARS
    run_row["try_chrome"] = "yes" if record["result"] != "ok" or thin else ""
    run_row["snapshot_file"] = record["snapshot_file"]
    run_row["text_file"] = record["text_file"]
    return record, run_row


def main():
    rows = approved_rows()
    if "--only" in sys.argv:
        wanted = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        unknown = wanted - {row["source_id"] for row in rows}
        if unknown:
            sys.exit(f"not approved or not in registry: {sorted(unknown)}")
        rows = [row for row in rows if row["source_id"] in wanted]

    if "--list" in sys.argv:
        for row in rows:
            print(f"{row['source_id']:42} {row['url']}")
        print(f"{len(rows)} pages would be fetched")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    last_request_time = 0.0
    last_request_by_host = {}
    run_rows = []
    for number, row in enumerate(rows, start=1):
        host = urllib.parse.urlparse(row["url"].strip()).netloc.lower()
        wait_politely(host, last_request_time, last_request_by_host)
        record, run_row = fetch_one(session, row, manifest)
        last_request_time = time.monotonic()
        last_request_by_host[host] = last_request_time
        manifest.append(record)
        save_manifest(manifest)  # after every request, so an interrupted run keeps its records
        run_rows.append(run_row)
        print(f"[{number}/{len(rows)}] {row['source_id']}: {run_row['result']} "
              f"{run_row.get('http_status', '')} changed={run_row.get('changed', '')}")

    with open(LAST_RUN_PATH, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LAST_RUN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(run_rows)

    counts = {}
    for run_row in run_rows:
        key = run_row["result"] if run_row["result"] != "ok" else f"ok/changed={run_row['changed']}"
        counts[key] = counts.get(key, 0) + 1
    print("summary:", counts)
    print(f"per-source results: {LAST_RUN_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
