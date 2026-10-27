"""Download candidate documents from the Chicago Board of Elections (CBOE) candidates page.

Saves, verbatim, under data/raw/cboe/ (gitignored):
  - the candidates page HTML itself, once per run, named by retrieval time
  - every linked document whose link text matches CBOE_DOCUMENT_PATTERNS

Documents are never overwritten. CBOE puts a timestamp in the file name of
each new filing report (e.g. "Candidate Filing Report_20261026174516936.pdf"),
so later reports land next to earlier ones and can be compared. A document
already on disk under the same name is skipped (re-run safe).

Every download is recorded in data/raw/cboe/manifest.json: URL, link text,
local path, retrieved_at (UTC), HTTP status, bytes, sha256, Last-Modified.

Usage:
  python scripts/fetch_cboe.py
"""

import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration — every choice about what to fetch lives here.
# ---------------------------------------------------------------------------

CBOE_CANDIDATES_PAGE = "https://chicagoelections.gov/getting-ballot/candidates"

# Link texts (case-insensitive regular expressions) whose documents we keep.
# Checked against the page on 2026-10-27; the link texts then were
#   "Candidate Filing Report", "Click here for the full Candidate List for ...",
#   "Ballot Placement Lottery Results for ...", "Library of Electoral Board Decisions",
#   "Index of Electoral Board Decisions".
# Forms (waivers, subpoenas, ...) and guides are deliberately not fetched.
CBOE_DOCUMENT_PATTERNS = [
    r"candidate filing report",
    r"candidate list",
    r"ballot placement lottery",
    r"electoral board decisions",
]

# The CBOE web server and its blob storage have rejected non-browser clients
# in the past (WebFetch got 403 on related sites), so send a browser User-Agent.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Pause between document downloads, to be polite to the server.
SECONDS_BETWEEN_REQUESTS = 2

REQUEST_TIMEOUT_SECONDS = 60

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "cboe"
DOCUMENTS_DIR = OUTPUT_DIR / "documents"
PAGES_DIR = OUTPUT_DIR / "pages"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


def utc_now_text():
    """Current UTC time as ISO-8601 text, to the second."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest():
    """Return the list of earlier download records (empty on first run)."""
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return []


def save_manifest(records):
    MANIFEST_PATH.write_text(json.dumps(records, indent=2) + "\n")


def local_path_for(document_url):
    """Local path for a document: documents/<blob folder>/<original file name>.

    The blob URLs look like .../prod/2026-10/<name>.pdf; the "2026-10" folder
    is kept so two documents with the same name in different months don't collide.
    URLs on other hosts (app.chicagoelections.com/...) use their last folder name.
    """
    url_path = urllib.parse.unquote(urllib.parse.urlparse(document_url).path)
    path_parts = [part for part in url_path.split("/") if part]
    file_name = path_parts[-1]
    folder_name = path_parts[-2] if len(path_parts) >= 2 else "root"
    return DOCUMENTS_DIR / folder_name / file_name


def download(session, url):
    """GET a URL; return (response, content bytes). Raises on HTTP errors."""
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response, response.content


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCUMENTS_DIR.mkdir(exist_ok=True)
    PAGES_DIR.mkdir(exist_ok=True)
    manifest = load_manifest()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    # 1. The candidates page itself, saved every run (it changes as CBOE posts new lists).
    retrieved_at = utc_now_text()
    page_response, page_bytes = download(session, CBOE_CANDIDATES_PAGE)
    page_path = PAGES_DIR / f"candidates_page_{retrieved_at.replace(':', '')}.html"
    page_path.write_bytes(page_bytes)
    manifest.append({
        "kind": "page",
        "url": CBOE_CANDIDATES_PAGE,
        "local_path": str(page_path.relative_to(OUTPUT_DIR)),
        "retrieved_at": retrieved_at,
        "http_status": page_response.status_code,
        "bytes": len(page_bytes),
        "sha256": hashlib.sha256(page_bytes).hexdigest(),
    })
    print(f"page: {CBOE_CANDIDATES_PAGE} -> {page_path.name} ({len(page_bytes):,} bytes)")

    # 2. Find links whose text matches one of the patterns.
    soup = BeautifulSoup(page_bytes, "html.parser")
    wanted_links = []
    for anchor in soup.find_all("a", href=True):
        link_text = anchor.get_text(" ", strip=True)
        if any(re.search(pattern, link_text, re.IGNORECASE) for pattern in CBOE_DOCUMENT_PATTERNS):
            # Hrefs contain raw spaces; quote them so requests sends a valid URL.
            absolute_url = urllib.parse.urljoin(CBOE_CANDIDATES_PAGE, anchor["href"])
            quoted_url = urllib.parse.quote(urllib.parse.unquote(absolute_url), safe=":/?&=%")
            wanted_links.append((link_text, quoted_url))
    print(f"{len(wanted_links)} matching document links")

    # 3. Download each one not already on disk.
    for link_text, document_url in wanted_links:
        destination = local_path_for(document_url)
        if destination.exists():
            print(f"  skip (already have): {destination.relative_to(OUTPUT_DIR)}")
            continue
        time.sleep(SECONDS_BETWEEN_REQUESTS)
        retrieved_at = utc_now_text()
        response, content = download(session, document_url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        manifest.append({
            "kind": "document",
            "link_text": link_text,
            "url": document_url,
            "local_path": str(destination.relative_to(OUTPUT_DIR)),
            "retrieved_at": retrieved_at,
            "http_status": response.status_code,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "last_modified": response.headers.get("Last-Modified"),
        })
        print(f"  got: {destination.relative_to(OUTPUT_DIR)} ({len(content):,} bytes)")

    save_manifest(manifest)
    print(f"manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
