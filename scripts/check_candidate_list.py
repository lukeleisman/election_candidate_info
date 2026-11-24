"""Check our frozen candidate table against CBOE's newest official Candidate List.

Rule (user, 2026-11-24): between now and the election the only expected change is candidates dropping off
(successful objections, withdrawals). So:
  - a candidate of ours who is no longer on the newest list -> "not_on_list" (the page greys them out);
  - ANY other difference -> flagged for the user (data/candidates/candidate_list_flags.csv); the page is
    not changed for it. Examples: a name on the list we don't have, a spelling change, a status word
    we haven't seen, a line the parser can't read.
  - "Challenged" is NOT shown on the page (user, 2026-11-24); it is kept in the output for reference.
Candidate IDs never change here: data/candidates/candidates_cboe.csv is frozen (user, 2026-11-24).

Inputs:
  data/candidates/candidates_cboe.csv            frozen candidate table (IDs)
  data/candidates/duplicate_filings.csv          second filings by the same person (left out)
  data/candidates/candidate_list_name_matches_manual.csv   user answers to name flags (hand-edited)
  data/candidates/ballot_status.csv              Electoral Board decisions, when published (reason text)
  data/raw/cboe/manifest.json + documents/       from scripts/fetch_cboe.py (make fetch-cboe)

Outputs:
  data/candidates/candidate_list_check.csv       one row per candidate of ours: list_result + evidence
  data/candidates/candidate_list_flags.csv       everything for the user to review (empty = nothing)
  data/candidates/candidate_list_checked.json    which list was used and when CBOE was last checked
                                                 (read by scripts/build_dashboard.py for "Checked <date>")

Usage:
  python scripts/check_candidate_list.py
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber

from names import normalization_steps_on, normalize_name

# ---------------------------------------------------------------------------
# Configuration — every judgment call lives here.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
DUPLICATE_FILINGS_PATH = REPO_ROOT / "data" / "candidates" / "duplicate_filings.csv"
NAME_MATCHES_MANUAL_PATH = REPO_ROOT / "data" / "candidates" / "candidate_list_name_matches_manual.csv"
BALLOT_STATUS_PATH = REPO_ROOT / "data" / "candidates" / "ballot_status.csv"
CBOE_RAW_DIR = REPO_ROOT / "data" / "raw" / "cboe"
CBOE_MANIFEST_PATH = CBOE_RAW_DIR / "manifest.json"

CHECK_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "candidate_list_check.csv"
FLAGS_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "candidate_list_flags.csv"
CHECKED_OUTPUT_PATH = REPO_ROOT / "data" / "candidates" / "candidate_list_checked.json"

# Which downloaded PDFs are candidate lists for THIS election: file name pattern + text on page 1.
# (CBOE's 10/27/2026 "Candidate List" was for the Nov 3, 2026 election and must not be used.)
CANDIDATE_LIST_FILE_GLOB = "Candidate List_*.pdf"
ELECTION_TEXT_ON_FIRST_PAGE = "February 23, 2027"
# "Status as of 11/9/2026 4:01:16 PM" on page 1: the list's own date. The newest list = latest status date.
STATUS_AS_OF_PATTERN = re.compile(r"Status as of (\d{1,2}/\d{1,2}/\d{4})")

# A line starting with one of these (and not containing "Vote") starts a new race.
OFFICE_HEADER_PREFIXES = ("Mayor", "Clerk", "Treasurer", "Alderperson", "Council Member")
# Everything after this line is referenda, not candidates.
END_OF_CANDIDATES_LINE = "Referenda and Local Options"

# Status words at the end of a candidate line. Seen on the 11/9/2026 list: Candidate, Challenged.
# Both mean "on the list". OPEN QUESTION: how CBOE marks a removed / withdrawn candidate (name dropped,
# or a new word such as "Removed" / "Withdrawn"). Until seen, any other word makes the line unreadable
# and it is FLAGGED (never guessed). When a new word appears, add it to the right list here.
ON_LIST_STATUS_WORDS = ["Candidate", "Challenged"]
OFF_LIST_STATUS_WORDS = []   # e.g. ["Removed", "Withdrawn"] once seen; such rows count as "not_on_list"
KNOWN_STATUS_WORDS = ON_LIST_STATUS_WORDS + OFF_LIST_STATUS_WORDS

# Lines that are neither candidates nor addresses and carry no information. Anything else unreadable is flagged.
IGNORED_LINE_PATTERNS = [
    r"^Vote for ",
    r"^Write-in N/A$",
    r"^No Candidate N/A$",            # a race with nobody filed (one Police District Council on 11/9)
    r"Page \d+ of \d+$",              # page footer "Monday, November 9, 2026 Page 1 of 18"
    r"^This Official candidate list", r"^of the City of Chicago", r"^Status as of ",
    r"^Candidate Filings in Ballot Order", r"^Ballot No\.Candidate Status",
]
# Address lines under aldermanic candidates end in a 5-digit ZIP code.
ADDRESS_LINE_PATTERN = re.compile(r"\d{5}$")

# How a race on the list maps to our office_code + district_number.
OFFICE_CODE_BY_PREFIX = {"Mayor": "MAYOR", "Clerk": "CLERK", "Treasurer": "TREAS",
                         "Alderperson": "ALD", "Council Member": "PDC"}
DISTRICT_NUMBER_PATTERN = re.compile(r"(\d+)(?:st|nd|rd|th)\b")

# Name matching within a race. Only rule applied automatically: identical name after
# scripts/names.py normalization (the same steps used everywhere in this repo). Every other pairing
# comes from the user's answers in NAME_MATCHES_MANUAL_PATH (column same_person = yes / no).
# A candidate of ours with no match is "not_on_list" ONLY when the list has no unmatched name left in
# that race AND no unreadable line in that race (otherwise it may be a spelling change or a new status
# word: "needs_review", flagged, page unchanged).
NOT_ON_LIST_NEEDS_NO_UNMATCHED_LIST_NAMES_IN_RACE = True

CHECK_COLUMNS = ["candidate_id", "office_code", "district_number", "ballot_name_raw", "list_result",
                 "list_ballot_name", "list_status", "match_method", "removal_reason", "list_file",
                 "list_status_as_of", "normalization_steps_on"]
FLAG_COLUMNS = ["flag_type", "race", "candidate_id", "our_ballot_name", "list_ballot_name", "list_status",
                "detail", "list_file"]


# ---------------------------------------------------------------------------
# Reading the list
# ---------------------------------------------------------------------------

def pdf_lines(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages).splitlines()


def find_newest_list():
    """(path, status_as_of 'M/D/YYYY') of the newest Candidate List for this election, from the manifest."""
    manifest = json.loads(CBOE_MANIFEST_PATH.read_text())
    candidates = []
    for row in manifest:
        if row.get("kind") != "document":
            continue
        path = CBOE_RAW_DIR / row["local_path"]
        if not path.match(CANDIDATE_LIST_FILE_GLOB) and not path.match(CANDIDATE_LIST_FILE_GLOB.replace(".pdf", "__*.pdf")):
            continue
        first_lines = "\n".join(pdf_lines(path)[:6])
        if ELECTION_TEXT_ON_FIRST_PAGE not in first_lines:
            continue
        status = STATUS_AS_OF_PATTERN.search(first_lines)
        if not status:
            raise SystemExit(f"{path}: no 'Status as of' date on page 1")
        month, day, year = (int(part) for part in status.group(1).split("/"))
        candidates.append(((year, month, day), row["retrieved_at"], path, status.group(1)))
    if not candidates:
        raise SystemExit(f"No '{CANDIDATE_LIST_FILE_GLOB}' with '{ELECTION_TEXT_ON_FIRST_PAGE}' in {CBOE_MANIFEST_PATH}")
    candidates.sort()
    _, _, path, status_as_of = candidates[-1]
    return path, status_as_of


def race_key(office_header):
    """'Alderperson, 23rd Ward' -> ('ALD', '23'); 'Mayor' -> ('MAYOR', '')."""
    prefix = next(p for p in OFFICE_HEADER_PREFIXES if office_header.startswith(p))
    district = DISTRICT_NUMBER_PATTERN.search(office_header)
    return OFFICE_CODE_BY_PREFIX[prefix], (str(int(district.group(1))) if district else "")


def parse_list(path):
    """Candidate rows [(race, ballot_name, status)] and unreadable lines [(race or None, line)]."""
    status_pattern = re.compile(r"^(.*\S)\s+(" + "|".join(map(re.escape, KNOWN_STATUS_WORDS)) + r")\s*$")
    rows, unreadable = [], []
    race = None
    for line in pdf_lines(path):
        text = line.strip()
        if not text:
            continue
        if text == END_OF_CANDIDATES_LINE:
            break
        if text.startswith(OFFICE_HEADER_PREFIXES) and "Vote" not in text:
            race = race_key(text)
            continue
        if any(re.search(pattern, text) for pattern in IGNORED_LINE_PATTERNS):
            continue
        match = status_pattern.match(text)
        if match and race:
            rows.append((race, match.group(1), match.group(2)))
        elif race and ADDRESS_LINE_PATTERN.search(text):
            continue
        else:
            unreadable.append((race, text))
    return rows, unreadable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def race_text(race):
    return race[0] + ("-" + race[1] if race[1] else "")


def main():
    list_path, status_as_of = find_newest_list()
    list_file = str(list_path.relative_to(CBOE_RAW_DIR))
    list_rows, unreadable = parse_list(list_path)
    print(f"newest list: {list_file} (status as of {status_as_of}): {len(list_rows)} candidate rows")

    duplicates = {row["candidate_id"] for row in read_csv(DUPLICATE_FILINGS_PATH)}
    ours = [row for row in read_csv(CANDIDATES_PATH) if row["candidate_id"] not in duplicates]
    # User answers: (candidate_id, list_ballot_name) -> same_person yes / no.
    manual = {(row["candidate_id"], row["list_ballot_name"]): row["same_person"].strip().lower()
              for row in read_csv(NAME_MATCHES_MANUAL_PATH)}
    decisions = {row["candidate_id"]: row.get("matched_decisions", "") for row in read_csv(BALLOT_STATUS_PATH)}

    list_by_race = defaultdict(list)
    for race, name, status in list_rows:
        list_by_race[race].append({"name": name, "status": status, "used": False})
    ours_by_race = defaultdict(list)
    for row in ours:
        ours_by_race[(row["office_code"], row["district_number"])].append(row)

    results, flags = {}, []
    races_with_unreadable_lines = {race for race, _ in unreadable}
    for race in sorted(set(list_by_race) | set(ours_by_race)):
        on_list = list_by_race[race]
        # 1. Identical after normalization (one list row per candidate).
        # 2. User-confirmed pairs from NAME_MATCHES_MANUAL_PATH.
        for method in ["normalized_name", "user_confirmed"]:
            for row in ours_by_race[race]:
                if row["candidate_id"] in results:
                    continue
                for entry in on_list:
                    if entry["used"]:
                        continue
                    if method == "normalized_name":
                        same = normalize_name(entry["name"]) == normalize_name(row["ballot_name_raw"])
                    else:
                        same = manual.get((row["candidate_id"], entry["name"])) == "yes"
                    if same:
                        entry["used"] = True
                        off = entry["status"] in OFF_LIST_STATUS_WORDS
                        results[row["candidate_id"]] = {
                            "list_result": "not_on_list" if off else "on_list",
                            "list_ballot_name": entry["name"], "list_status": entry["status"],
                            "match_method": method,
                            "removal_reason": (f"Marked '{entry['status']}' on the Board of Elections list of "
                                               f"{status_as_of}") if off else ""}
                        break
        unmatched_list = [entry for entry in on_list if not entry["used"]]
        unmatched_ours = [row for row in ours_by_race[race] if row["candidate_id"] not in results]
        for row in unmatched_ours:
            if NOT_ON_LIST_NEEDS_NO_UNMATCHED_LIST_NAMES_IN_RACE and (unmatched_list or race in races_with_unreadable_lines):
                results[row["candidate_id"]] = {"list_result": "needs_review", "list_ballot_name": "",
                                                "list_status": "", "match_method": "none", "removal_reason": ""}
                if not unmatched_list:
                    flags.append({"flag_type": "missing_in_race_with_unreadable_line", "race": race_text(race),
                                  "candidate_id": row["candidate_id"], "our_ballot_name": row["ballot_name_raw"],
                                  "list_ballot_name": "", "list_status": "",
                                  "detail": "Not matched, and this race has a line the parser can't read (see "
                                            "unreadable_line). Not greyed out until you decide.",
                                  "list_file": list_file})
                for entry in unmatched_list:
                    flags.append({"flag_type": "name_differs_same_race", "race": race_text(race),
                                  "candidate_id": row["candidate_id"], "our_ballot_name": row["ballot_name_raw"],
                                  "list_ballot_name": entry["name"], "list_status": entry["status"],
                                  "detail": (f"Same person? Answer in {NAME_MATCHES_MANUAL_PATH.name} "
                                             "(same_person yes/no)."), "list_file": list_file})
            else:
                reason = f"Not on the Board of Elections candidate list of {status_as_of}"
                if decisions.get(row["candidate_id"]):
                    reason += f"; Electoral Board: {decisions[row['candidate_id']]}"
                results[row["candidate_id"]] = {"list_result": "not_on_list", "list_ballot_name": "",
                                                "list_status": "", "match_method": "none", "removal_reason": reason}
                # Shown to the user too (user: removals are greyed out, but should be seen).
                flags.append({"flag_type": "removed_from_list", "race": race_text(race),
                              "candidate_id": row["candidate_id"], "our_ballot_name": row["ballot_name_raw"],
                              "list_ballot_name": "", "list_status": "", "detail": reason + " (greyed out on page)",
                              "list_file": list_file})
        # List names nobody of ours matched, in races where all of ours are matched: a new filer?
        if not unmatched_ours:
            for entry in unmatched_list:
                flags.append({"flag_type": "on_list_not_in_our_table", "race": race_text(race), "candidate_id": "",
                              "our_ballot_name": "", "list_ballot_name": entry["name"], "list_status": entry["status"],
                              "detail": "Not in candidates_cboe.csv (frozen). New filer or a name we lack?",
                              "list_file": list_file})
    for race, text in unreadable:
        flags.append({"flag_type": "unreadable_line", "race": race_text(race) if race else "", "candidate_id": "",
                      "our_ballot_name": "", "list_ballot_name": "", "list_status": "",
                      "detail": f"Line not understood (new status word?): {text}", "list_file": list_file})

    steps = normalization_steps_on()
    with open(CHECK_OUTPUT_PATH, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CHECK_COLUMNS)
        writer.writeheader()
        for row in ours:
            writer.writerow({"candidate_id": row["candidate_id"], "office_code": row["office_code"],
                             "district_number": row["district_number"], "ballot_name_raw": row["ballot_name_raw"],
                             **results[row["candidate_id"]], "list_file": list_file,
                             "list_status_as_of": status_as_of, "normalization_steps_on": steps})
    with open(FLAGS_OUTPUT_PATH, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FLAG_COLUMNS)
        writer.writeheader()
        writer.writerows(flags)

    # "Checked" = the newest time fetch_cboe.py looked at the CBOE candidates page (it then also re-checks
    # every listed document, so the newest list on disk is the newest CBOE had at that moment).
    manifest = json.loads(CBOE_MANIFEST_PATH.read_text())
    page_checks = [row["retrieved_at"] for row in manifest if row.get("kind") == "page"]
    counts = defaultdict(int)
    for result in results.values():
        counts[result["list_result"]] += 1
    CHECKED_OUTPUT_PATH.write_text(json.dumps({
        "cboe_page_checked_at": max(page_checks), "list_file": list_file, "list_status_as_of": status_as_of,
        "result_counts": dict(counts), "flag_count": len(flags)}, indent=2) + "\n")

    print(f"results: {dict(counts)}; duplicate filings left out: {len(duplicates)}")
    print(f"{len(flags)} flag(s) -> {FLAGS_OUTPUT_PATH}")
    for flag in flags:
        print(f"  {flag['flag_type']}: {flag['race']} {flag['candidate_id']} "
              f"'{flag['our_ballot_name']}' vs list '{flag['list_ballot_name']}' {flag['detail'][:90]}")


if __name__ == "__main__":
    main()
