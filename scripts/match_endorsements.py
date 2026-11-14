"""Match endorsement rows to CBOE candidate_ids and build the per-candidate table (PLAN.md §4).

Input
  data/endorsements/endorsements_manual.csv   one row per endorsement claim, entered by hand or by an
                                              agent (docs/process_endorsement_research.md). Parser rows
                                              (endorsements_extracted.csv) will join here when parsers exist.
  data/candidates/candidates_cboe.csv         the official list (candidate_id, office_code, district_number)
Output
  data/endorsements/endorsements.csv          every input row + the proposed match and why
  data/tables/endorsements_by_candidate.csv   per candidate: counts by endorser type + endorser list,
                                              counting only rows that pass TABLE_FILTERS

Matching (broad rules; anything unusual is a judgment call, never auto-accepted; see MATCH_RULES):
  1. candidate_id filled in the input row  -> used as given (e.g. rows copied from a candidate's own
     site, or a judgment call the user confirmed by writing the id in).
  2. Otherwise the race comes from office_raw + ward_raw, and the name is compared to every candidate
     in that race with scripts/names.py normalization.
To confirm a judgment call: copy candidate_id_proposed into candidate_id in endorsements_manual.csv.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from names import (edit_distance, first_names_equivalent, normalization_steps_on,  # noqa: E402
                   normalize_name, quoted_nicknames)

# ---------------------------------------------------------------------------
# Configuration: every judgment call lives here.
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
MANUAL_PATH = REPO / "data" / "endorsements" / "endorsements_manual.csv"
CANDIDATES_PATH = REPO / "data" / "candidates" / "candidates_cboe.csv"
OUTPUT_PATH = REPO / "data" / "endorsements" / "endorsements.csv"
TABLE_PATH = REPO / "data" / "tables" / "endorsements_by_candidate.csv"

# Columns of endorsements_manual.csv (also its header). One row = one endorser backing one candidate.
MANUAL_COLUMNS = [
    "endorsement_row_id",   # unique, e.g. dsa2027-001; never reused
    "source_id",            # row in config/endorsement_sources.csv where it was seen
    "endorser_name",        # as written on the page
    "endorser_type",        # one of ENDORSER_TYPES (entered by hand; never guessed by code)
    "endorsement_kind",     # one of ENDORSEMENT_KINDS (added 2026-11-14)
    "candidate_name_raw",   # as written on the page (may be blank on a candidate's own page)
    "office_raw",           # e.g. "Alderperson", "Mayor", "Ward 26", "Police District Council 19"
    "ward_raw",             # ward or police district number as written; blank for citywide offices
    "candidate_id",         # optional: fill when certain (own page) or to confirm a judgment call
    "cycle",                # one of CYCLE_VALUES: does the source say this is for Feb 2027?
    "cycle_evidence",       # the words that show the cycle, e.g. heading "2027 Re-Election endorsements"
    "quote",                # verbatim text from the page that states the endorsement
    "url",                  # page where it was seen
    "snapshot_file",        # data/raw/endorsements/... file it was read from, if fetched
    "seen_on",              # date we read it (YYYY-MM-DD)
    "announced_on",         # date on the page, if any
    "entered_by",           # luke | claude_agent_<date> | parser:<name>
    "review_status",        # one of REVIEW_STATUSES
    "notes",
]

# Endorser types. Entered by hand per row; the table counts each type separately.
ENDORSER_TYPES = [
    "union",               # labor unions and councils (CFL, SEIU locals, trades)
    "advocacy_org",        # issue groups (Sierra Club, Abundant Housing, Equality IL, ...)
    "political_org",       # DSA, UWF, IVI-IPO, Indivisible chapters, PACs, voter guides
    "party_or_ward_org",   # Democratic ward organizations, committeepersons as an org
    "elected_official",    # a current officeholder, named as a person
    "former_official",     # former officeholders and former candidates
    "newspaper",           # editorial boards
    "business_org",        # chambers, realtors, industry associations
    "person",              # community members, business owners, anyone else
]

# What the row records (user, 2026-11-14, on Giannoulias appearing with Ald. Gardiner: "not an official
# endorsement ... but might be worth noting"). Shown on the page with a tag; not counted in the table.
ENDORSEMENT_KINDS = [
    "endorsement",              # the source says it endorses / backs the candidate
    "support_not_endorsement",  # public support short of an endorsement (appearance, praise); noted only
]

CYCLE_VALUES = ["2027", "older", "unclear"]

REVIEW_STATUSES = ["unreviewed", "reviewed", "rejected"]

# Which rows the per-candidate table counts. PLAN.md §4: reviewed rows only.
# OPEN QUESTION (user): also count unreviewed rows (shown as such) while review catches up?
TABLE_FILTERS = {
    "review_status": ["reviewed"],
    "cycle": ["2027"],
    "match_status": ["accepted"],
    "endorsement_kind": ["endorsement"],
}

# office_raw text (lowercased, contains) -> CBOE office_code. First hit wins, in this order.
OFFICE_RAW_TO_CODE = [
    ("police district", "PDC"),
    ("district council", "PDC"),
    ("mayor", "MAYOR"),
    ("clerk", "CLERK"),
    ("treasurer", "TREAS"),
    ("alder", "ALD"),      # alderman, alderperson, alderwoman
    ("ward", "ALD"),
    ("city council", "ALD"),
]
CITYWIDE_OFFICES = {"MAYOR", "CLERK", "TREAS"}

# Name rules, tried in order; the first that fits decides. Each rule's status (accepted | judgment_call)
# is a setting: change it here to accept or flag a whole class of matches.
MATCH_RULES = {
    "exact_normalized": "accepted",          # same name after names.py normalization
    "ballot_quoted_nickname": "accepted",    # 'Beth Rochford' vs ballot 'ELIZABETH "BETH" ROCHFORD' (nickname printed on the ballot)
    "hyphen_space_variant": "judgment_call", # 'Rodriguez-Sanchez' vs 'RODRIGUEZ SANCHEZ'
    "middle_name_dropped": "judgment_call",  # 'Anthony Quezada' vs 'ANTHONY JOEL QUEZADA' (same first and last word)
    "surname_and_nickname": "judgment_call", # same surname word + names.py NICKNAME_GROUPS first names ('Jenny'/'JENNIFER')
    "surname_only_unique": "judgment_call",  # surname word matches exactly one candidate in the race ('Erik'/'ERIC SMITH')
}
# Hyphens and spaces count the same when comparing surname words ("SIGCHO-LOPEZ" vs "SIGCHO LOPEZ").
TREAT_HYPHEN_AS_SPACE = True
# Unmatched rows list race candidates within this edit distance of the normalized name.
NEAR_MISS_MAX_EDIT_DISTANCE = 4

OUTPUT_EXTRA_COLUMNS = ["race_code", "candidate_id_proposed", "candidate_ballot_name", "match_rule",
                        "match_status", "match_notes", "normalization_steps"]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def race_of(row):
    """(office_code, district number as int or None) from office_raw/ward_raw, or (None, None)."""
    office_text = (row["office_raw"] or "").lower()
    office_code = next((code for needle, code in OFFICE_RAW_TO_CODE if needle in office_text), None)
    if office_code in CITYWIDE_OFFICES:
        return office_code, None
    number_match = re.search(r"\d+", row["ward_raw"] or "") or re.search(r"\d+", office_text)
    return office_code, int(number_match.group()) if number_match else None


def name_words(normalized_name):
    text = normalized_name.replace("-", " ") if TREAT_HYPHEN_AS_SPACE else normalized_name
    return text.split()


def match_name(name_raw, race_candidates):
    """(candidate or None, rule, status, notes) for one name against the candidates of one race.

    Rules are tried in MATCH_RULES order; a rule decides only if exactly one candidate fits it.
    """
    target = normalize_name(name_raw)
    if not target:
        return None, "", "unmatched", "no candidate name in the row"
    target_words = name_words(target)
    target_first, target_surname = target_words[0], target_words[-1]

    def ballot_words(candidate):
        return name_words(normalize_name(candidate["ballot_name_raw"]))

    rule_tests = {
        "exact_normalized": lambda cand: normalize_name(cand["ballot_name_raw"]) == target,
        "ballot_quoted_nickname": lambda cand: target_first in quoted_nicknames(cand["ballot_name_raw"])
            and ballot_words(cand)[-1] == target_surname,
        "hyphen_space_variant": lambda cand: ballot_words(cand) == target_words,
        "middle_name_dropped": lambda cand: len(ballot_words(cand)) > len(target_words)
            and ballot_words(cand)[0] == target_first and ballot_words(cand)[-1] == target_surname,
        "surname_and_nickname": lambda cand: target_surname in ballot_words(cand)[1:]
            and first_names_equivalent(target_first, ballot_words(cand)[0]),
        "surname_only_unique": lambda cand: target_surname in ballot_words(cand)[1:],
    }
    for rule, status in MATCH_RULES.items():
        fits = [cand for cand in race_candidates if rule_tests[rule](cand)]
        if len(fits) == 1:
            return fits[0], rule, status, f"name '{name_raw}' vs ballot '{fits[0]['ballot_name_raw']}'"
        if len(fits) > 1:
            return None, rule, "judgment_call", f"several candidates fit {rule}: " + \
                "; ".join(f"{cand['candidate_id']} {cand['ballot_name_raw']}" for cand in fits)

    near = sorted((edit_distance(target, normalize_name(cand["ballot_name_raw"])), cand["candidate_id"],
                   cand["ballot_name_raw"]) for cand in race_candidates)
    near_text = "; ".join(f"{cid} {name} (distance {distance})" for distance, cid, name in near
                          if distance <= NEAR_MISS_MAX_EDIT_DISTANCE)
    return None, "", "unmatched", ("near misses: " + near_text) if near_text else "no candidate close in this race"


def main():
    candidates = read_csv(CANDIDATES_PATH)
    by_id = {cand["candidate_id"]: cand for cand in candidates}
    if not MANUAL_PATH.exists():
        with open(MANUAL_PATH, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(MANUAL_COLUMNS)
        print(f"created empty {MANUAL_PATH.relative_to(REPO)}")
    rows = read_csv(MANUAL_PATH)

    problems = []
    seen_ids = set()
    for row in rows:
        if row["endorsement_row_id"] in seen_ids:
            problems.append(f"duplicate endorsement_row_id {row['endorsement_row_id']}")
        seen_ids.add(row["endorsement_row_id"])
        for column, allowed in [("endorser_type", ENDORSER_TYPES), ("endorsement_kind", ENDORSEMENT_KINDS),
                                ("cycle", CYCLE_VALUES),
                                ("review_status", REVIEW_STATUSES)]:
            if row[column] not in allowed:
                problems.append(f"{row['endorsement_row_id']}: {column}='{row[column]}' not in {allowed}")

    output_rows = []
    for row in rows:
        office_code, district = race_of(row)
        race_code = f"{office_code}-{district:02d}" if office_code and district is not None else (office_code or "")
        result = dict(row, race_code=race_code, normalization_steps=normalization_steps_on())
        given_id = row["candidate_id"].strip()
        if given_id:
            if given_id not in by_id:
                problems.append(f"{row['endorsement_row_id']}: candidate_id {given_id} not on the CBOE list")
                result.update(match_status="unmatched", match_rule="given", match_notes="given id not found")
            else:
                result.update(candidate_id_proposed=given_id, candidate_ballot_name=by_id[given_id]["ballot_name_raw"],
                              match_rule="given", match_status="accepted")
        elif not office_code:
            result.update(match_status="unmatched", match_notes="office not recognized from office_raw")
        else:
            race_candidates = [cand for cand in candidates if cand["office_code"] == office_code and
                               (office_code in CITYWIDE_OFFICES or
                                (cand["district_number"] and int(float(cand["district_number"])) == district))]
            candidate, rule, status, notes = match_name(row["candidate_name_raw"], race_candidates)
            result.update(match_rule=rule, match_status=status, match_notes=notes)
            if candidate:
                result.update(candidate_id_proposed=candidate["candidate_id"],
                              candidate_ballot_name=candidate["ballot_name_raw"])
        output_rows.append(result)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_COLUMNS + OUTPUT_EXTRA_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    # Per-candidate table: only rows passing TABLE_FILTERS.
    counted = [row for row in output_rows
               if all(row.get(column, "") in allowed for column, allowed in TABLE_FILTERS.items())]
    table = {}
    for row in counted:
        entry = table.setdefault(row["candidate_id_proposed"], {"rows": []})
        entry["rows"].append(row)
    table_columns = (["candidate_id", "ballot_name_raw", "endorsements_counted"]
                     + [f"n_{kind}" for kind in ENDORSER_TYPES] + ["endorsers", "endorsement_row_ids"])
    with open(TABLE_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=table_columns)
        writer.writeheader()
        for candidate_id in sorted(table):
            entry_rows = table[candidate_id]["rows"]
            line = {"candidate_id": candidate_id, "ballot_name_raw": by_id[candidate_id]["ballot_name_raw"],
                    "endorsements_counted": len(entry_rows),
                    "endorsers": "; ".join(r["endorser_name"] for r in entry_rows),
                    "endorsement_row_ids": "; ".join(r["endorsement_row_id"] for r in entry_rows)}
            for kind in ENDORSER_TYPES:
                line[f"n_{kind}"] = sum(r["endorser_type"] == kind for r in entry_rows)
            writer.writerow(line)

    status_counts = {}
    for row in output_rows:
        status_counts[row.get("match_status", "")] = status_counts.get(row.get("match_status", ""), 0) + 1
    print(f"rows: {len(output_rows)}; match status: {status_counts}")
    print(f"counted in table (filters {TABLE_FILTERS}): {len(counted)} rows, {len(table)} candidates")
    for row in output_rows:
        if row.get("match_status") != "accepted":
            print(f"  {row['match_status']:13} {row['endorsement_row_id']}: '{row['candidate_name_raw']}' "
                  f"{row['race_code']} -> {row.get('candidate_id_proposed', '')} {row.get('match_notes', '')}")
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  " + problem)
        sys.exit(1)


if __name__ == "__main__":
    main()
