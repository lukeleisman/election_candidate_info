"""Prototype: rebuild today's ISBE bulk files from our previous copy + only the bytes that changed.

NOT part of the pipeline yet. Used once (2026-11-24) to test whether an incremental fetch gives a file
byte-identical to a full download. See README.md next to this file.

Method, per file:
  1. Sanity samples: compare SAMPLE_COUNT evenly spaced CHUNK_BYTES ranges of our copy with the server's file.
  2. Binary search (range requests of CHUNK_BYTES) for the first chunk that differs. Assumption to be tested:
     everything before it is unchanged.
  3. Download the server's file from that offset to the end; output = our bytes before it + downloaded bytes.
  4. The server's Last-Modified must be the same at the start and the end, otherwise the file changed mid-way.

Inputs:  data/raw/isbe/<file> (previous full download; NOT modified)
Outputs: data/raw/isbe_incremental_test/<file> (gitignored) + incremental_result.json next to this script.

Run from the repo root:
  /opt/anaconda3/envs/election-candidate-info/bin/python analysis/2026-11-24_isbe_incremental_probe/build_incremental_copy.py
"""

import hashlib
import json
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
ISBE_BASE_URL = "https://www.elections.il.gov/CampaignDisclosureDataFiles/"
PREVIOUS_COPY_DIR = REPO_ROOT / "data" / "raw" / "isbe"
OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "isbe_incremental_test"
RESULT_PATH = Path(__file__).resolve().parent / "incremental_result.json"

# The three large files (the small ones are cheap to download whole).
FILES_TO_TEST = ["Receipts.txt", "FiledDocs.txt", "D2Totals.txt"]

CHUNK_BYTES = 2000             # size of each comparison range request
SAMPLE_COUNT = 10              # evenly spaced sanity samples before the binary search
SECONDS_BETWEEN_REQUESTS = 1   # politeness pause between small range requests
REQUEST_TIMEOUT_SECONDS = 300

# Same browser User-Agent as scripts/fetch_isbe.py (ISBE refused other clients on 2026-10-04).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def get_range(url, start, end=None):
    """Bytes start..end (inclusive) of the server file, uncompressed; also returns the response headers."""
    byte_range = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT, "Range": byte_range,
                                          "Accept-Encoding": "identity"}, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 206:
        raise SystemExit(f"{url}: expected 206 Partial Content, got {response.status_code}")
    time.sleep(SECONDS_BETWEEN_REQUESTS)
    return response.content, response.headers


def same_as_server(url, local_file, offset):
    server_bytes, _ = get_range(url, offset, offset + CHUNK_BYTES - 1)
    local_file.seek(offset)
    return server_bytes == local_file.read(CHUNK_BYTES)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_one(file_name):
    url = ISBE_BASE_URL + file_name
    previous_path = PREVIOUS_COPY_DIR / file_name
    previous_size = previous_path.stat().st_size
    _, first_headers = get_range(url, 0, 0)
    last_modified_at_start = first_headers.get("Last-Modified")
    server_size = int(first_headers["Content-Range"].split("/")[1])
    requests_made = 1

    with open(previous_path, "rb") as local_file:
        # 1. Sanity samples (last possible start = previous_size - CHUNK_BYTES).
        sample_offsets = [round(i * (previous_size - CHUNK_BYTES) / (SAMPLE_COUNT - 1)) for i in range(SAMPLE_COUNT)]
        sample_results = {}
        for offset in sample_offsets:
            sample_results[offset] = same_as_server(url, local_file, offset)
            requests_made += 1
        # 2. Binary search between the last matching sample and the first non-matching one.
        first_mismatch = next((o for o in sample_offsets if not sample_results[o]), None)
        if first_mismatch is None:
            low, high = previous_size - CHUNK_BYTES, previous_size  # whole copy matches: new bytes only appended
        else:
            matching_before = [o for o in sample_offsets if o < first_mismatch and sample_results[o]]
            if not matching_before:
                low, high = None, 0     # differs from the very start: incremental not possible
            else:
                low, high = matching_before[-1], first_mismatch
                while high - low > CHUNK_BYTES:
                    middle = (low + high) // 2
                    requests_made += 1
                    if same_as_server(url, local_file, middle):
                        low = middle
                    else:
                        high = middle
        # Any sample AFTER the first mismatch that matches again = bytes shifted back into place; recorded raw.
        matches_after_first_mismatch = [o for o in sample_offsets
                                        if first_mismatch is not None and o > first_mismatch and sample_results[o]]
        keep_bytes = 0 if low is None else low + CHUNK_BYTES if first_mismatch is None else low

        # 3. Our bytes before keep_bytes + server bytes from keep_bytes to the end.
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / file_name
        local_file.seek(0)
        with open(output_path, "wb") as output_file:
            remaining = keep_bytes
            while remaining:
                block = local_file.read(min(remaining, 1024 * 1024))
                output_file.write(block)
                remaining -= len(block)
            downloaded, last_headers = get_range(url, keep_bytes) if keep_bytes < server_size else (b"", first_headers)
            requests_made += 1
            output_file.write(downloaded)

    # 4. Did the server file change while we worked?
    last_modified_at_end = last_headers.get("Last-Modified")
    result = {
        "file": file_name, "previous_size": previous_size, "server_size": server_size,
        "output_size": output_path.stat().st_size, "kept_from_previous_bytes": keep_bytes,
        "downloaded_bytes": len(downloaded), "requests_made": requests_made,
        "sample_results": {str(k): v for k, v in sample_results.items()},
        "samples_matching_after_first_mismatch": matches_after_first_mismatch,
        "last_modified_at_start": last_modified_at_start, "last_modified_at_end": last_modified_at_end,
        "server_changed_during_build": last_modified_at_start != last_modified_at_end,
        "output_sha256": sha256_of(output_path),
    }
    print(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    results = [build_one(name) for name in FILES_TO_TEST]
    RESULT_PATH.write_text(json.dumps(results, indent=1))
    print("results ->", RESULT_PATH)
