"""Append one row (JSON object on stdin) to the Google-pass output CSV.
Fills ballot_name_raw/office_code/ward from the candidate file and the fixed
provenance fields; refuses duplicates."""
import csv, json, os, sys
REPO = "/Users/lleisman/Luke/github/chicagoindata/election_candidate_info-endorsements"
CANDIDATES_CSV = f"{REPO}/data/candidates/candidates_cboe.csv"
EARLIER_CSV = f"{REPO}/data/endorsements/candidate_campaign_sites.csv"
OUTPUT_CSV = f"{REPO}/data/endorsements/candidate_campaign_sites_google.csv"
TODAY = "2026-11-12"
FIXED_FIELDS = {"found_via": "google_chrome", "checked_on": TODAY,
                "entered_by": f"claude_agent_{TODAY}", "review_status": "unreviewed"}
ALLOWED_STATUS = {"found", "needs_confirmation", "ambiguous", "none_found"}
columns = next(csv.reader(open(EARLIER_CSV)))
entries = json.load(sys.stdin)
if isinstance(entries, dict):
    entries = [entries]
candidates = {r["candidate_id"]: r for r in csv.DictReader(open(CANDIDATES_CSV))}
exists = os.path.exists(OUTPUT_CSV)
done = {r["candidate_id"] for r in csv.DictReader(open(OUTPUT_CSV))} if exists else set()
with open(OUTPUT_CSV, "a", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns)
    if not exists:
        writer.writeheader()
    for entry in entries:
        cid = entry["candidate_id"]
        assert cid not in done, f"duplicate {cid}"
        assert entry["status"] in ALLOWED_STATUS, entry["status"]
        unknown = set(entry) - set(columns)
        assert not unknown, unknown
        cand = candidates[cid]
        row = {c: "" for c in columns}
        row.update({"ballot_name_raw": cand["ballot_name_raw"], "office_code": cand["office_code"],
                    "ward": cand["district_number"]})
        row.update(FIXED_FIELDS)
        row.update(entry)
        writer.writerow(row)
        done.add(cid)
        print("appended", cid, row["status"])

# Stamp the retrieval time into this candidate's raw Google files: the raw file is
# written with "retrieved: __NOW__" immediately after the search; this replaces the
# placeholder with the current local time (seconds to a few minutes after retrieval).
import datetime, glob
RAW_DIR = f"{REPO}/data/raw/google_search"
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
for entry in entries:
    for path in glob.glob(f"{RAW_DIR}/{entry['candidate_id']}*.txt"):
        text = open(path).read()
        if "retrieved: __NOW__" in text:
            open(path, "w").write(text.replace("retrieved: __NOW__", f"retrieved: {now}", 1))
            print("stamped", os.path.basename(path), now)
