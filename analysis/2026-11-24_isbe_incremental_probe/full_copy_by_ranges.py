"""Full copy of one ISBE file fetched in byte ranges (used 2026-11-24 when the plain full download of
Receipts.txt timed out twice with no response in 120 s). Independent of the incremental method: every byte comes
from the server. Output: data/raw/isbe_full_by_ranges_test/<file> (gitignored); result JSON next to this script.

Run from the repo root:
  /opt/anaconda3/envs/election-candidate-info/bin/python analysis/2026-11-24_isbe_incremental_probe/full_copy_by_ranges.py Receipts.txt
"""
import hashlib, json, sys, time
from pathlib import Path
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
ISBE_BASE_URL = "https://www.elections.il.gov/CampaignDisclosureDataFiles/"
OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "isbe_full_by_ranges_test"
RANGE_BYTES = 50 * 1024 * 1024        # size of each piece
SECONDS_BETWEEN_REQUESTS = 1          # politeness pause between pieces
REQUEST_TIMEOUT_SECONDS = 300
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")   # as scripts/fetch_isbe.py

file_name = sys.argv[1]
url = ISBE_BASE_URL + file_name
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
output_path = OUTPUT_DIR / file_name
digest = hashlib.sha256()
offset, total, last_modified_values, started = 0, None, set(), time.time()
with open(output_path, "wb") as output_file:
    while total is None or offset < total:
        end = offset + RANGE_BYTES - 1
        response = requests.get(url, headers={"User-Agent": USER_AGENT, "Range": f"bytes={offset}-{end}",
                                              "Accept-Encoding": "identity"}, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code != 206:
            raise SystemExit(f"expected 206, got {response.status_code} at offset {offset}")
        total = int(response.headers["Content-Range"].split("/")[1])
        last_modified_values.add(response.headers.get("Last-Modified"))
        output_file.write(response.content); digest.update(response.content)
        offset += len(response.content)
        print(f"{offset:,} / {total:,} bytes", flush=True)
        time.sleep(SECONDS_BETWEEN_REQUESTS)
result = {"file": file_name, "bytes": offset, "server_size": total, "sha256": digest.hexdigest(),
          "last_modified_values_seen": sorted(v for v in last_modified_values if v),
          "server_changed_during_download": len(last_modified_values) > 1, "seconds": round(time.time() - started)}
Path(__file__).with_name(f"full_by_ranges_{file_name}.json").write_text(json.dumps(result, indent=1))
print(json.dumps(result, indent=1))
