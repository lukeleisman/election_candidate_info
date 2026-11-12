"""Check the hand-entered incumbents table and write the (i) column for the dashboard.

The hand table (user decision 2026-11-12, option a) names who holds each seat now and which
ballot candidate, if any, is that person. This script never edits it; it prints every problem
and exits 1 so `make` stops.

FUTURE ELECTIONS: this table is for the Feb 23, 2027 election only (seats as held in Nov 2026).
For a later election, make a new table from that time's officeholders (INCUMBENTS_PATH);
candidate IDs and ward numbers in this file will not carry over.

Inputs:
  data/input/incumbents_manual.csv            hand table, one row per race (columns below)
  data/tables/display_candidates.csv          ballot filings (make display-tables runs first)
  data/raw/city/ward_offices_htai-wnw4.json   City data portal "Ward Offices" (make fetch-ward-offices),
                                              used only as a cross-check of the alder names
Output:
  data/tables/incumbents.csv                  candidate_id, race_key, officeholder_name, source_url

Hand table columns:
  race_key            MAYOR, CLERK, TREAS, ALD-01 ... ALD-50
  officeholder_name   as written in the source
  candidate_id        the ballot candidate who is this officeholder; blank = not on the ballot
  ballot_name         copy of that candidate's ballot name, for reading only
  match_note          how the candidate_id was chosen (seeded 2026-11-12 by last name in race)
  source_url, source_checked_on, entered_by, notes

Checks (printed):
  - every race in REQUIRED_RACE_KEYS has exactly one row
  - candidate_id exists and is in the same race
  - the officeholder's last name appears in that candidate's ballot name (NAME_CHECK)
  - blank candidate_id: any ballot candidate in the race whose name contains the last name
  - alder names differ from the City data portal file (printed only; not a failure, since the
    portal can lag behind appointments)

Usage:
  python scripts/check_incumbents.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from names import normalize_name  # noqa: E402  (same name rules as the committee matching)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
INCUMBENTS_PATH = REPO_ROOT / "data" / "input" / "incumbents_manual.csv"
CANDIDATES_PATH = REPO_ROOT / "data" / "tables" / "display_candidates.csv"
WARD_OFFICES_PATH = REPO_ROOT / "data" / "raw" / "city" / "ward_offices_htai-wnw4.json"
OUTPUT_PATH = REPO_ROOT / "data" / "tables" / "incumbents.csv"

# Races that must have a row (the offices on the dashboard).
REQUIRED_RACE_KEYS = ["MAYOR", "CLERK", "TREAS"] + [f"ALD-{ward:02d}" for ward in range(1, 51)]

# NAME_CHECK: the officeholder's last name (text before the first comma when written
# "Last, First"; otherwise the last word), after names.normalize_name with spaces and hyphens
# removed, must appear inside the normalized ballot name (also without spaces and hyphens).
# Catches 'Rodriguez Sanchez, Rossana' vs 'ROSSANA RODRÍGUEZ SÁNCHEZ'.
NAME_CHECK = "last_name_inside_ballot_name_after_normalize"

# ---------------------------------------------------------------------------


def squeeze(name):
    """normalize_name, then drop spaces and hyphens."""
    return normalize_name(name).replace(" ", "").replace("-", "")


def last_name(officeholder_name):
    """'Cardona, Jr., Felix' -> 'Cardona'; 'Anna M. Valencia' -> 'Valencia'."""
    if "," in officeholder_name:
        return officeholder_name.split(",")[0]
    return officeholder_name.split()[-1]


def main():
    incumbents = pd.read_csv(INCUMBENTS_PATH, dtype=str, keep_default_na=False)
    candidates = pd.read_csv(CANDIDATES_PATH, dtype=str, keep_default_na=False)
    by_id = candidates.set_index("candidate_id")
    problems = []

    # One row per race.
    counts = incumbents["race_key"].value_counts()
    for race_key in REQUIRED_RACE_KEYS:
        if counts.get(race_key, 0) != 1:
            problems.append(f"{race_key}: {counts.get(race_key, 0)} rows (need 1)")
    for race_key in sorted(set(incumbents["race_key"]) - set(REQUIRED_RACE_KEYS)):
        problems.append(f"{race_key}: not a dashboard race")

    for row in incumbents.itertuples():
        surname = squeeze(last_name(row.officeholder_name))
        if row.candidate_id:
            if row.candidate_id not in by_id.index:
                problems.append(f"{row.race_key}: candidate_id {row.candidate_id} not on the ballot list")
                continue
            candidate = by_id.loc[row.candidate_id]
            if candidate["race_key"] != row.race_key:
                problems.append(f"{row.race_key}: {row.candidate_id} is in race {candidate['race_key']}")
            if surname not in squeeze(candidate["ballot_name_raw"]):
                problems.append(f"{row.race_key}: '{row.officeholder_name}' vs ballot name "
                                f"'{candidate['ballot_name_raw']}' fails {NAME_CHECK}")
        else:
            race = candidates[candidates["race_key"] == row.race_key]
            possible = race[race["ballot_name_raw"].map(squeeze).str.contains(surname, regex=False)]
            note = f"possible: {possible['candidate_id'].tolist()}" if len(possible) else "no ballot name contains the last name"
            print(f"not on the ballot: {row.race_key} {row.officeholder_name} ({note})")
            if len(possible):
                problems.append(f"{row.race_key}: candidate_id blank but {note}")

    # Cross-check alder names against the City data portal (printed only).
    if WARD_OFFICES_PATH.exists():
        portal = {f"ALD-{int(office['ward']):02d}": office["alderman"] for office in json.loads(WARD_OFFICES_PATH.read_text())}
        for row in incumbents[incumbents["race_key"].str.startswith("ALD-")].itertuples():
            if squeeze(portal.get(row.race_key, "")) != squeeze(row.officeholder_name):
                print(f"differs from City data portal: {row.race_key} table '{row.officeholder_name}' "
                      f"vs portal '{portal.get(row.race_key, '(none)')}'")
    else:
        print(f"NOTE: {WARD_OFFICES_PATH.relative_to(REPO_ROOT)} missing; portal cross-check skipped")

    output = incumbents[incumbents["candidate_id"] != ""][["candidate_id", "race_key", "officeholder_name", "source_url"]]
    output.to_csv(OUTPUT_PATH, index=False)
    print(f"{len(incumbents)} races; {len(output)} incumbents on the ballot; wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)


if __name__ == "__main__":
    main()
