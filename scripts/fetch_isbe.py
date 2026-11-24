"""Download the Illinois State Board of Elections (ISBE) campaign-disclosure bulk files.

Source: https://www.elections.il.gov/CampaignDisclosureDataFiles/ — tab-delimited
text files, refreshed daily (Receipts.txt was ~1.06 GB on 2026-10-04). Field
definitions: CampaignDisclosureDataDictionary.txt (also fetched).

Files are saved verbatim to data/raw/isbe/ (gitignored). The latest copy of
each file replaces the previous one (they are daily snapshots of a whole
database); the manifest keeps a record of every download.

A file is skipped when the server's Last-Modified header equals the one recorded
for the last download of that file (SKIP_IF_UNCHANGED). Pass --force to download anyway.

How files are downloaded (user, 2026-11-24: "download the small incremental changes"):
  - INCREMENTAL_FILES (the big ones) are updated from our previous copy: ISBE rewrites only the recent end of
    each file, so we find where our copy and the server's file first differ (small byte-range requests) and
    download only from there to the end. Receipts.txt: ~24 MB instead of 1.07 GB for 4 days of changes.
    Tested 2026-11-24 against full downloads of the same server version: FiledDocs.txt and D2Totals.txt
    byte-identical (analysis/2026-11-24_isbe_incremental_probe/).
    OPEN QUESTION: an edit EARLIER in the file that keeps its length would not be found. FULL_COPY_EVERY_DAYS
    sets how often a full copy is taken anyway (user's choice; see below).
  - Everything else, a first download, or a file whose very start differs: a full copy, fetched in
    RANGE_PIECE_BYTES pieces (a plain full GET of Receipts.txt timed out twice on 2026-11-24: ISBE's server is
    slow to start sending a whole file; pieces start at once).
  - Either way the file is written to <file>.partial and only replaces the old copy when complete, the size
    equals the server's, and the server's Last-Modified did not change while we worked.

Manifest: data/raw/isbe/manifest.json — per download: file, URL, retrieved_at
(UTC), Last-Modified, HTTP status, bytes, sha256, data_rows (lines minus header).

Usage:
  python scripts/fetch_isbe.py            # all files in FILES_TO_FETCH
  python scripts/fetch_isbe.py --force
  python scripts/fetch_isbe.py --full     # full copies (in pieces) even of INCREMENTAL_FILES
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

# Files updated incrementally from our previous copy (see the module docstring). Others are fetched whole.
INCREMENTAL_FILES = ["Receipts.txt", "FiledDocs.txt", "D2Totals.txt"]
# Size of each comparison request, and how many evenly spaced comparisons are made before the search for the
# first difference (an early sample that differs = the start of the file changed -> full copy instead).
COMPARE_CHUNK_BYTES = 2000
COMPARE_SAMPLE_COUNT = 10
SECONDS_BETWEEN_SMALL_REQUESTS = 1      # pause between the small comparison requests
# Full copies are fetched in pieces of this size, SECONDS_BETWEEN_REQUESTS apart.
RANGE_PIECE_BYTES = 50 * 1024 * 1024
RANGE_REQUEST_TIMEOUT_SECONDS = 300
# Take a full copy of an incremental file anyway when its last full copy is older than this many days.
# None = never (user, 2026-11-24: "for now ... assume we just need to download the small incremental changes").
# OPEN QUESTION for the user: set a number (e.g. 30) once the Receipts.txt comparison is in.
FULL_COPY_EVERY_DAYS = None

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


def get_range(session, url, start, end=None):
    """Bytes start..end (inclusive; end None = to the end of the file), uncompressed. Returns (bytes, headers)."""
    byte_range = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
    response = session.get(url, headers={"Range": byte_range, "Accept-Encoding": "identity"},
                           timeout=RANGE_REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 206:
        raise SystemExit(f"{url}: asked for {byte_range}, expected 206 Partial Content, got {response.status_code}")
    return response.content, response.headers


def server_facts(session, url):
    """(file size, Last-Modified) from a 1-byte range request (a HEAD request timed out once, 2026-11-24)."""
    _, headers = get_range(session, url, 0, 0)
    return int(headers["Content-Range"].split("/")[1]), headers.get("Last-Modified")


def first_difference(session, url, previous_path):
    """Byte offset up to which our previous copy equals the server file (None = differs at the start).

    Compares COMPARE_SAMPLE_COUNT evenly spaced chunks, then searches between the last matching sample and the
    first differing one. Returns the start of the last chunk known to match, so a little more is downloaded
    than strictly needed. Returns (offset or None, requests made, samples {offset: same?}).
    """
    previous_size = previous_path.stat().st_size
    requests_made = 0
    with open(previous_path, "rb") as previous_file:
        def same_at(offset):
            nonlocal requests_made
            server_bytes, _ = get_range(session, url, offset, offset + COMPARE_CHUNK_BYTES - 1)
            requests_made += 1
            time.sleep(SECONDS_BETWEEN_SMALL_REQUESTS)
            previous_file.seek(offset)
            return server_bytes == previous_file.read(COMPARE_CHUNK_BYTES)
        last_start = previous_size - COMPARE_CHUNK_BYTES
        offsets = [round(i * last_start / (COMPARE_SAMPLE_COUNT - 1)) for i in range(COMPARE_SAMPLE_COUNT)]
        samples = {offset: same_at(offset) for offset in offsets}
        differing = [offset for offset in offsets if not samples[offset]]
        if not differing:
            return previous_size, requests_made, samples          # nothing changed: only new bytes appended
        if differing[0] == offsets[0]:
            return None, requests_made, samples                   # the start differs: take a full copy
        low = max(offset for offset in offsets if offset < differing[0])
        high = differing[0]
        while high - low > COMPARE_CHUNK_BYTES:
            middle = (low + high) // 2
            if same_at(middle):
                low = middle
            else:
                high = middle
        return low, requests_made, samples


def days_since_last_full_copy(manifest, file_name):
    """Days since the newest manifest record of file_name made by a full copy; None if there is none."""
    for record in reversed(manifest):
        if record["file"] == file_name and record.get("method", "full") in ("full", "full_by_ranges"):
            retrieved = datetime.strptime(record["retrieved_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - retrieved).days
    return None


def download_file(session, file_name, manifest, force_full=False):
    """Update one file (incrementally when possible, else a full copy in pieces); return its manifest record."""
    url = ISBE_BASE_URL + file_name
    destination = OUTPUT_DIR / file_name
    partial_path = destination.with_suffix(destination.suffix + ".partial")
    retrieved_at = utc_now_text()
    server_size, last_modified_at_start = server_facts(session, url)

    keep_bytes, compare_requests, method = 0, 0, "full_by_ranges"
    full_copy_age = days_since_last_full_copy(manifest, file_name)
    full_copy_due = (FULL_COPY_EVERY_DAYS is not None
                     and (full_copy_age is None or full_copy_age >= FULL_COPY_EVERY_DAYS))
    if file_name in INCREMENTAL_FILES and destination.exists() and not force_full and not full_copy_due:
        offset, compare_requests, samples = first_difference(session, url, destination)
        if offset is None:
            print(f"  start of {file_name} differs from our copy: full copy instead")
        else:
            keep_bytes, method = min(offset, server_size), "incremental"

    # Our bytes before keep_bytes, then the server's bytes from keep_bytes on, in pieces.
    downloaded_bytes = 0
    with open(partial_path, "wb") as output_file:
        if keep_bytes:
            with open(destination, "rb") as previous_file:
                remaining = keep_bytes
                while remaining:
                    block = previous_file.read(min(remaining, DOWNLOAD_CHUNK_BYTES))
                    output_file.write(block)
                    remaining -= len(block)
        offset = keep_bytes
        last_modified_at_end = last_modified_at_start
        while offset < server_size:
            piece, headers = get_range(session, url, offset, offset + RANGE_PIECE_BYTES - 1)
            last_modified_at_end = headers.get("Last-Modified")
            if last_modified_at_end != last_modified_at_start:
                break
            output_file.write(piece)
            offset += len(piece)
            downloaded_bytes += len(piece)
            if offset < server_size:
                print(f"    {offset:,} / {server_size:,} bytes", flush=True)
                time.sleep(SECONDS_BETWEEN_REQUESTS)

    # Checks before the old copy is replaced. On failure the .partial file is left for inspection.
    if last_modified_at_end != last_modified_at_start:
        raise SystemExit(f"{file_name}: ISBE replaced the file while we downloaded it (Last-Modified "
                         f"{last_modified_at_start} -> {last_modified_at_end}). Run again.")
    if partial_path.stat().st_size != server_size:
        raise SystemExit(f"{file_name}: built {partial_path.stat().st_size:,} bytes, server has {server_size:,}")

    sha256, newline_count = hashlib.sha256(), 0
    with open(partial_path, "rb") as built_file:
        for block in iter(lambda: built_file.read(DOWNLOAD_CHUNK_BYTES), b""):
            sha256.update(block)
            newline_count += block.count(b"\n")
    partial_path.replace(destination)
    return {
        "file": file_name,
        "url": url,
        "retrieved_at": retrieved_at,
        "last_modified": last_modified_at_start,
        "http_status": 206,
        "bytes": server_size,
        "sha256": sha256.hexdigest(),
        # Lines minus the header line. A text field containing a newline would
        # inflate this; the build scripts report their own parsed row counts.
        "data_rows": max(newline_count - 1, 0) if file_name != "CampaignDisclosureDataDictionary.txt" else None,
        # How the file was built (added 2026-11-24). Older records have no "method": they were plain full GETs.
        "method": method,
        "kept_from_previous_bytes": keep_bytes,
        "downloaded_bytes": downloaded_bytes,
        "compare_requests": compare_requests,
    }


def main():
    arguments = sys.argv[1:]
    force = "--force" in arguments
    force_full = "--full" in arguments          # full copy even for INCREMENTAL_FILES
    requested = [argument for argument in arguments if argument not in ("--force", "--full")] or FILES_TO_FETCH
    unknown = set(requested) - set(FILES_TO_FETCH) - set(ON_REQUEST_FILES)
    if unknown:
        raise SystemExit(f"not in FILES_TO_FETCH or ON_REQUEST_FILES: {sorted(unknown)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    for file_name in requested:
        if SKIP_IF_UNCHANGED and not force and (OUTPUT_DIR / file_name).exists():
            _, server_modified = server_facts(session, ISBE_BASE_URL + file_name)
            if server_modified and server_modified == last_recorded_modified(manifest, file_name):
                print(f"skip (unchanged since {server_modified}): {file_name}")
                continue
        print(f"downloading {file_name} ...", flush=True)
        record = download_file(session, file_name, manifest, force_full=force_full)
        manifest.append(record)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  {record['method']}: {record['downloaded_bytes']:,} of {record['bytes']:,} bytes downloaded, "
              f"{record['data_rows']} data rows, Last-Modified {record['last_modified']}")
        time.sleep(SECONDS_BETWEEN_REQUESTS)


if __name__ == "__main__":
    main()
