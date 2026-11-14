"""Print the next N candidates not yet in the Google-pass output, with the query URL
and a compact view of the earlier (websearch) row for comparison.
Usage: python3 next.py [N]"""
import csv, os, sys, re, urllib.parse
# Repo root = two folders up from this file (moved from the endorsements worktree 2026-11-13).
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANDIDATES_CSV = f"{REPO}/data/candidates/candidates_cboe.csv"
EARLIER_CSV = f"{REPO}/data/endorsements/candidate_campaign_sites.csv"
OUTPUT_CSV = f"{REPO}/data/endorsements/candidate_campaign_sites_google.csv"
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
count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
candidates = [r for r in csv.DictReader(open(CANDIDATES_CSV)) if r["office_code"] in OFFICE_CODES]
pending = [r for r in candidates if r["candidate_id"] not in done]
print(f"done {len(done)} / {len(candidates)}; pending {len(pending)}")
for row in pending[:count]:
    query = build_query(row)
    old = earlier.get(row["candidate_id"], {})
    print("---")
    print(row["candidate_id"], "|", row["ballot_name_raw"])
    print("query:", query)
    print("url: https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    print("earlier:", {k: old.get(k) for k in ("status", "campaign_site_url", "ward_office_url", "other_site_urls", "notes") if old.get(k)})
