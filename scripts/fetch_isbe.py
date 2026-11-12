"""Download the Illinois State Board of Elections (ISBE) campaign-disclosure bulk files.

Source: https://www.elections.il.gov/CampaignDisclosureDataFiles/ — tab-delimited
text files, refreshed daily (Receipts.txt was ~1.06 GB on 2026-10-04). Field
definitions: CampaignDisclosureDataDictionary.txt (also fetched).

Files are saved verbatim to data/raw/isbe/ (gitignored). The latest copy of
each file replaces the previous one (they are daily snapshots of a whole
database); the manifest keeps a record of every download.

A file is skipped when the server's Last-Modified header equals the one recorded
for the last download of that file (SKIP_IF_UNCHANGED). Pass --force to download anyway.

Manifest: data/raw/isbe/manifest.json — per download: file, URL, retrieved_at
(UTC), Last-Modified, HTTP status, bytes, sha256, data_rows (lines minus header).

Usage:
  python scripts/fetch_isbe.py            # all files in FILES_TO_FETCH
  python scripts/fetch_isbe.py --force
  python scripts/fetch_isbe.py Committees.txt Candidates.txt   # only these
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ISBE_BASE_URL = "https://www.elections.il.gov/CampaignDisclosureDataFiles/"

# Every file listed in the data dictionary that this project uses, plus the
# dictionary itself. Investments / Officers / PrevOfficers / CmteOfficerLinks
# are not used yet and are left out. Expenditures.txt (~790 MB, ~25 min at ISBE's
# ~0.5 MB/s) was dropped 2026-11-12 (user): no script reads it. To get it again, add it back
# here or run: python scripts/fetch_isbe.py Expenditures.txt (allowed by ON_REQUEST_FILES).
FILES_TO_FETCH = [
    "CampaignDisclosureDataDictionary.txt",
    "Candidates.txt",
    "CanElections.txt",
    "CmteCandidateLinks.txt",
    "Committees.txt",
    "FiledDocs.txt",
    "D2Totals.txt",
    "Receipts.txt",
]

# Files fetched only when named on the command line (not part of a plain run / make fetch-isbe).
ON_REQUEST_FILES = ["Expenditures.txt"]

# WebFetch was refused (403) on 2026-10-04; curl with a browser User-Agent worked.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

SECONDS_BETWEEN_REQUESTS = 2
REQUEST_TIMEOUT_SECONDS = 120
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
SKIP_IF_UNCHANGED = True

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "isbe"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


def utc_now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest():
    return json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else []


def last_recorded_modified(manifest, file_name):
    """Last-Modified recorded at the most recent download of file_name, or None."""
    for record in reversed(manifest):
        if record["file"] == file_name:
            return record.get("last_modified")
    return None


def download_file(session, file_name):
    """Stream one file to disk; return its manifest record."""
    url = ISBE_BASE_URL + file_name
    destination = OUTPUT_DIR / file_name
    partial_path = destination.with_suffix(destination.suffix + ".partial")
    retrieved_at = utc_now_text()
    sha256 = hashlib.sha256()
    total_bytes = 0
    newline_count = 0
    with session.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with open(partial_path, "wb") as output_file:
            for chunk in response.iter_content(DOWNLOAD_CHUNK_BYTES):
                output_file.write(chunk)
                sha256.update(chunk)
                total_bytes += len(chunk)
                newline_count += chunk.count(b"\n")
        last_modified = response.headers.get("Last-Modified")
        status = response.status_code
    # Only replace the previous copy once the download finished.
    partial_path.replace(destination)
    return {
        "file": file_name,
        "url": url,
        "retrieved_at": retrieved_at,
        "last_modified": last_modified,
        "http_status": status,
        "bytes": total_bytes,
        "sha256": sha256.hexdigest(),
        # Lines minus the header line. A text field containing a newline would
        # inflate this; the build scripts report their own parsed row counts.
        "data_rows": max(newline_count - 1, 0) if file_name != "CampaignDisclosureDataDictionary.txt" else None,
    }


def main():
    arguments = sys.argv[1:]
    force = "--force" in arguments
    requested = [argument for argument in arguments if argument != "--force"] or FILES_TO_FETCH
    unknown = set(requested) - set(FILES_TO_FETCH) - set(ON_REQUEST_FILES)
    if unknown:
        raise SystemExit(f"not in FILES_TO_FETCH or ON_REQUEST_FILES: {sorted(unknown)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for file_name in requested:
        if SKIP_IF_UNCHANGED and not force and (OUTPUT_DIR / file_name).exists():
            head = session.head(ISBE_BASE_URL + file_name, timeout=REQUEST_TIMEOUT_SECONDS)
            server_modified = head.headers.get("Last-Modified")
            if server_modified and server_modified == last_recorded_modified(manifest, file_name):
                print(f"skip (unchanged since {server_modified}): {file_name}")
                continue
        print(f"downloading {file_name} ...", flush=True)
        record = download_file(session, file_name)
        manifest.append(record)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  {record['bytes']:,} bytes, {record['data_rows']} data rows, Last-Modified {record['last_modified']}")
        time.sleep(SECONDS_BETWEEN_REQUESTS)


if __name__ == "__main__":
    main()
