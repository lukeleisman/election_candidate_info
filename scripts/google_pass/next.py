"""Print the next N candidates not yet in the Google-pass output, with the query URL
and a compact view of the earlier row for comparison (first pass: the websearch row;
social_rerun: the first Google row).
Usage: python3 next.py [N] [--pass first|social_rerun]   (passes defined in passes.py)"""
import csv, os, sys, re, urllib.parse
from passes import PASSES, pass_from_argv
PASS_NAME, ARGS = pass_from_argv(sys.argv)
PASS = PASSES[PASS_NAME]
# Repo root = two folders up from this file (moved from the endorsements worktree 2026-11-13).
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANDIDATES_CSV = f"{REPO}/data/candidates/candidates_cboe.csv"
EARLIER_CSV = PASS["earlier_csv"]
OUTPUT_CSV = PASS["output_csv"]
# Offices in scope (per task instructions)
OFFICE_CODES = ("MAYOR", "CLERK", "TREAS", "ALD")
# Quote the office phrase? True until 2026-11-13 (102 candidates, through ALD-27-004). The quotes kept
# only pages with the exact phrase, which dropped social profiles whose bio doesn't say it (user found
# instagram.com/punkin_p and a LinkedIn profile for Raynetta Greenleaf in an unquoted search).
# False from ALD-27-005 on (user, 2026-11-13): RAYNETTA GREENLEAF Chicago 17th ward alderman
QUOTE_OFFICE_PHRASE = False
# Office phrase appended to the query (per task instructions)
OFFICE_PHRASE = {"MAYOR": "mayor", "CLERK": "city clerk", "TREAS": "city treasurer"}

def ordinal(number):
    """1 -> 1st, 2 -> 2nd, 11 -> 11th, 22 -> 22nd."""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"

def query_name(ballot_name):
    """Ballot name with the quoted nickname dropped, e.g. TIMOTHY "TIM" THOMAS JR. -> TIMOTHY THOMAS JR."""
    return re.sub(r'\s+', ' ', re.sub(r'"[^"]*"', '', ballot_name)).strip()

def build_query(row):
    if row["office_code"] == "ALD":
        phrase = f'{ordinal(int(row["district_number"]))} ward alderman'
    else:
        phrase = OFFICE_PHRASE[row["office_code"]]
    if QUOTE_OFFICE_PHRASE:
        phrase = f'"{phrase}"'
    return f'{query_name(row["ballot_name_raw"])} Chicago {phrase}'

done = set()
if os.path.exists(OUTPUT_CSV):
    done = {r["candidate_id"] for r in csv.DictReader(open(OUTPUT_CSV))}
earlier = {r["candidate_id"]: r for r in csv.DictReader(open(EARLIER_CSV))}
count = int(ARGS[1]) if len(ARGS) > 1 else 3
candidates = [r for r in csv.DictReader(open(CANDIDATES_CSV)) if r["office_code"] in OFFICE_CODES]
# A pass may stop at a given candidate (candidates_cboe.csv order), e.g. social_rerun = the first 102.
if PASS["last_candidate_id"]:
    ids = [r["candidate_id"] for r in candidates]
    candidates = candidates[:ids.index(PASS["last_candidate_id"]) + 1]
pending = [r for r in candidates if r["candidate_id"] not in done]
print(f"pass {PASS_NAME}: done {len(done)} / {len(candidates)}; pending {len(pending)}")
suffix = PASS["raw_suffix"]
print(f"raw files: data/raw/google_search/<id>{suffix}.txt (second search <id>{suffix or '_'}2.txt)")
for row in pending[:count]:
    query = build_query(row)
    old = earlier.get(row["candidate_id"], {})
    print("---")
    print(row["candidate_id"], "|", row["ballot_name_raw"])
    print("query:", query)
    print("url: https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    print("earlier:", {k: old.get(k) for k in ("status", "campaign_site_url", "ward_office_url", "other_site_urls", "endorsements_seen_raw", "notes") if old.get(k)})
