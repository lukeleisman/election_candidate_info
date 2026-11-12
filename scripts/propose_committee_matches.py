"""List every ISBE committee that could belong to each CBOE candidate — evidence only.

This script never picks anything. Next steps (PLAN.md §3a):
  scripts/build_isbe_record_review.py  -> you confirm CBOE candidate -> ISBE record
  scripts/build_candidate_committee.py -> committees of confirmed records + name matches

Inputs:
  data/candidates/candidates_cboe.csv
  data/raw/isbe/{Candidates,CanElections,CmteCandidateLinks,Committees}.txt  (scripts/fetch_isbe.py)

Two kinds of evidence (column evidence_source):
  "cmte_candidate_link": ISBE has a candidate record for a Chicago office of the
      same kind (ISBE_OFFICES_BY_CBOE_CODE), whose last name matches the CBOE name
      (LAST_NAME_RULE), and ISBE's CmteCandidateLinks ties a committee to that
      record. This is the official ISBE link (the electionssimplified audit warns
      against guessing committees by name — docs/plans/plan-illinois-local-finance.md
      in shu1513/electionssimplified).
  "committee_name_contains": a committee whose name contains both the first and
      the last word of the CBOE name (normalized). Listed whether or not ISBE also
      links it (changed 2026-10-27: scripts/build_candidate_committee.py decides
      which name matches are "name_only", i.e. not ISBE-linked to an accepted
      record). Catches committees ISBE has no link for, e.g. new candidates.
Candidates with neither get one row with evidence_source = "none".

Each row carries evidence columns (district match, first-name match, 2027
election record, committee status / creation date) so the choice can be made
row by row. Row order: candidate, then evidence_source, then committee ID.

Output:
  data/crosswalk/candidate_committee_proposals.csv   regenerated every run

Only candidates whose office_code is in COMMITTEE_STEP_OFFICE_CODES are included.
Duplicate filings (one person filed twice for the same race) are merged: rows of
data/candidates/duplicate_filings.csv are dropped here, and the kept filing lists
them in column also_filed_as. That file is hand-entered (user decision
2026-10-27: combine duplicate filings); candidates_cboe.csv keeps all filings so
it still matches the CBOE report total.

Usage:
  python scripts/propose_committee_matches.py
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from names import name_suffixes, normalization_steps_on, normalize_name

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
CBOE_CANDIDATES_PATH = REPO_ROOT / "data" / "candidates" / "candidates_cboe.csv"
DUPLICATE_FILINGS_PATH = REPO_ROOT / "data" / "candidates" / "duplicate_filings.csv"
ISBE_DIR = REPO_ROOT / "data" / "raw" / "isbe"
PROPOSALS_OUTPUT_PATH = REPO_ROOT / "data" / "crosswalk" / "candidate_committee_proposals.csv"

# Offices included in the committee step. Police District Council ("PDC") is left
# out for now (user decision 2026-10-27, PLAN.md §3a); add "PDC" to include it.
COMMITTEE_STEP_OFFICE_CODES = {"ALD", "MAYOR", "CLERK", "TREAS"}

# ISBE text files are tab-delimited, Windows-encoded. Undecodable bytes are
# replaced (shown as �) rather than stopping the run.
ISBE_FILE_ENCODING = "cp1252"

# ISBE `Office` values counted as the same office as each CBOE office code.
# Values seen in Candidates.txt on 2026-10-27 (counts statewide): Alderperson 2499,
# Alderman 14, Mayor 1710, Police District Council 85, Clerk / Treasurer (many towns).
ISBE_OFFICES_BY_CBOE_CODE = {
    "ALD": {"Alderperson", "Alderman"},
    "MAYOR": {"Mayor"},
    "CLERK": {"Clerk"},
    "TREAS": {"Treasurer"},
    "PDC": {"Police District Council"},
}
# OPEN QUESTION (user's; held 2026-11-04, may add later): records for OTHER offices are
# never proposed, so a candidate whose only ISBE record is for another office is missed.
# Example: MICHAEL PATRICK MURPHY (ALD-37-003) — ISBE 53754 is "President, Cook", at his
# CBOE mailing address; his committee 40838 arrives only as name_only. A possible rule:
# also propose other-office records whose address matches the CBOE mailing address
# (strictness of the address match not decided). See docs/process_committee_review.md.

# ISBE `District` must look like Chicago, optionally followed by a ward/district
# number: "Chicago", "Chicago 2", "Chicago-7", "Chicago 18 ". This excludes
# "Chicago Heights", "Chicago Ridge", "North Chicago", "South Chicago Heights".
CHICAGO_DISTRICT_PATTERN = re.compile(r"^\s*Chicago\s*(?:[-\s]\s*(\d+))?\s*$", re.IGNORECASE)

# Some records give the district as a bare number ("27"), with no city — 138
# Alderperson / Police District Council records statewide on 2026-10-27, 65 of
# them with a Chicago address, many of them 2027 challengers (e.g. Walter R
# Burnett, ISBE 53650; Bill Thanoukos, 53984). Such a record counts as Chicago
# when its address City (lowercased, trimmed) is in this set. ASSUMPTION: a
# candidate for another town's ward does not have a Chicago mailing address.
# Widened 2026-11-12: an ordinal and/or "Ward" is allowed too ("6th", "6th Ward"); seen on
# Allyson Renee Scrutchens, ISBE 54196 (District "6th", address "Redaction Requested").
BARE_NUMBER_DISTRICT_PATTERN = re.compile(r"^\s*(\d+)\s*(?:st|nd|rd|th)?\s*(?:ward)?\s*$", re.IGNORECASE)
BARE_NUMBER_DISTRICT_ADDRESS_CITIES = {"chicago"}

# Added 2026-11-12 (user: broader rules, anything fishy to manual review): a number-only
# district whose address City is blank (e.g. "Redaction Requested") also counts as
# Chicago, with district_basis = BARE_NUMBER_NO_ADDRESS_BASIS. The town can't be told,
# so scripts/apply_isbe_record_rule.py never auto-accepts these (UNCERTAIN_DISTRICT_BASES).
# False = drop them as before.
BARE_NUMBER_DISTRICT_NO_ADDRESS_COUNTS = True
BARE_NUMBER_NO_ADDRESS_BASIS = "bare_number_and_no_address"

# Last-name rule: the ISBE LastName, normalized (scripts/names.py), must appear
# as a run of whole words inside the normalized CBOE ballot name. Handles
# multi-word surnames ("LA SPATA", "RODRIGUEZ SANCHEZ"). Suffixes ("Jr") are
# dropped by the normalization.
LAST_NAME_RULE = "isbe_last_name_words_inside_cboe_name"

# Looser last-name matches (added 2026-11-12, user). Each one that is on is tried in this
# order, after the exact LAST_NAME_RULE. The kind of match is written to column
# last_name_match_type, and scripts/apply_isbe_record_rule.py never auto-accepts a row
# whose type is not "exact_words". User: "if the order doesn't match (or anytime there
# is something weird) we can proceed with the match, but should make sure it's flagged
# for human confirmation."
#   hyphen_space_differs  split hyphens into separate words on both sides, then apply
#                         LAST_NAME_RULE. Ballot "SIGCHO-LOPEZ" vs ISBE "Sigcho Lopez"
#                         (28403). Side effect: ISBE "Ward" now matches ballot
#                         "GUNN-WARD" (as ISBE "Ross" already matches "HEALY ROSS").
#   word_order_differs    every ISBE last-name word (hyphens split) is a ballot word,
#                         in any order. Ballot "LEAH CUNNINGHAM POUW" vs ISBE
#                         "Pouw Cunningham" (54055).
LOOSE_LAST_NAME_MATCHES_ON = {
    "hyphen_space_differs": True,
    "word_order_differs": True,
}
EXACT_LAST_NAME_MATCH_TYPE = "exact_words"

# For "committee_name_contains": a hyphenated last ballot word ("SIGCHO-LOPEZ") matches
# a committee name that has the hyphenated word OR every part as its own word ("Sigcho
# Lopez"). Added 2026-11-12. False = the hyphenated word must appear as written.
COMMITTEE_NAME_SEARCH_SPLITS_HYPHENS = True

# For "committee_name_contains": only committees whose Status is in this set.
# The dictionary says "Active or Final", but the file codes them "A" / "F"
# (2026-10-27: A 4,524, F 29,685). Linked committees are listed whatever their status.
NAME_SEARCH_COMMITTEE_STATUSES = {"A"}

# Election year of this race in CanElections (shown as evidence, not a filter).
# ISBE codes Chicago's February municipal election as CP (Consolidated Primary)
# and the April runoff as CE: e.g. Brian Hopkins (ISBE 28160) has
# "2023 CP; 2019 CP; 2015 CP; 2015 CE" (2015 = the year he was in a runoff).
# Checked 2026-10-27 on that one record; all 2027 codes are shown, not filtered.
ELECTION_YEAR = "2027"

OUTPUT_COLUMNS = [
    "candidate_id", "office_code", "district_number", "ballot_name_raw", "also_filed_as",
    "evidence_source",
    "isbe_candidate_id", "isbe_last_name", "isbe_first_name", "isbe_office", "isbe_district_raw",
    "isbe_district_number", "isbe_district_basis", "last_name_match_type",
    "district_matches", "first_word_matches",
    "suffix_matches",
    "isbe_election_records", f"has_{ELECTION_YEAR}_election_record",
    "committee_id", "committee_name", "committee_type", "committee_status",
    "committee_status_date", "committee_creation_date",
    "candidates_linked_to_committee",
    "normalization_steps_on",
]


def read_isbe(file_name):
    return pd.read_csv(
        ISBE_DIR / file_name, sep="\t", dtype=str, quoting=csv.QUOTE_NONE,
        encoding=ISBE_FILE_ENCODING, encoding_errors="replace", keep_default_na=False,
    )


def words_inside(needle_words, haystack_words):
    """True if needle_words appears as a contiguous run within haystack_words."""
    length = len(needle_words)
    if length == 0:
        return False
    return any(haystack_words[i:i + length] == needle_words for i in range(len(haystack_words) - length + 1))


def split_hyphens(words):
    """['BYRON', 'SIGCHO-LOPEZ'] -> ['BYRON', 'SIGCHO', 'LOPEZ']."""
    return [part for word in words for part in word.split("-") if part]


def last_name_match_type(isbe_last_name_words, cboe_words):
    """How the ISBE last name matches the ballot name: EXACT_LAST_NAME_MATCH_TYPE, one of
    the LOOSE_LAST_NAME_MATCHES_ON types (first that applies), or None for no match."""
    if words_inside(isbe_last_name_words, cboe_words):
        return EXACT_LAST_NAME_MATCH_TYPE
    isbe_parts, cboe_parts = split_hyphens(isbe_last_name_words), split_hyphens(cboe_words)
    if LOOSE_LAST_NAME_MATCHES_ON["hyphen_space_differs"] and words_inside(isbe_parts, cboe_parts):
        return "hyphen_space_differs"
    if LOOSE_LAST_NAME_MATCHES_ON["word_order_differs"] and isbe_parts and set(isbe_parts) <= set(cboe_parts):
        return "word_order_differs"
    return None


def committee_name_has_word(committee_words, ballot_word):
    """True if the ballot word is in the committee name; with COMMITTEE_NAME_SEARCH_SPLITS_HYPHENS,
    a hyphenated ballot word also counts when each part is a word of the (hyphen-split) name."""
    if ballot_word in committee_words:
        return True
    if COMMITTEE_NAME_SEARCH_SPLITS_HYPHENS and "-" in ballot_word:
        committee_parts = set(split_hyphens(committee_words))
        return all(part in committee_parts for part in split_hyphens([ballot_word]))
    return False


def main():
    candidates = pd.read_csv(CBOE_CANDIDATES_PATH, dtype=str, keep_default_na=False)
    candidates_all_ids = candidates["candidate_id"].tolist()
    in_scope = candidates["office_code"].isin(COMMITTEE_STEP_OFFICE_CODES)
    print(f"CBOE candidates in the committee step: {int(in_scope.sum())} of {len(candidates)} "
          f"(offices {sorted(COMMITTEE_STEP_OFFICE_CODES)}); left out by office: "
          f"{candidates.loc[~in_scope, 'office_code'].value_counts().to_dict()}")
    candidates = candidates[in_scope]

    # Merge duplicate filings into the filing named in same_person_as.
    duplicates = pd.read_csv(DUPLICATE_FILINGS_PATH, dtype=str, keep_default_na=False)
    unknown_ids = (set(duplicates["candidate_id"]) | set(duplicates["same_person_as"])) - set(candidates_all_ids)
    if unknown_ids:
        print(f"WARNING: duplicate_filings.csv names candidate IDs not in candidates_cboe.csv: {sorted(unknown_ids)}")
    also_filed_as = duplicates.groupby("same_person_as")["candidate_id"].agg(lambda ids: "; ".join(sorted(ids)))
    is_duplicate = candidates["candidate_id"].isin(duplicates["candidate_id"])
    print(f"duplicate filings merged into an earlier filing: "
          f"{candidates.loc[is_duplicate, 'candidate_id'].tolist()}")
    candidates = candidates[~is_duplicate].copy()
    candidates["also_filed_as"] = candidates["candidate_id"].map(also_filed_as).fillna("")
    isbe_candidates = read_isbe("Candidates.txt")
    isbe_elections = read_isbe("CanElections.txt")
    isbe_links = read_isbe("CmteCandidateLinks.txt")
    committees = read_isbe("Committees.txt")
    print(f"ISBE rows: Candidates {len(isbe_candidates):,}, CanElections {len(isbe_elections):,}, "
          f"CmteCandidateLinks {len(isbe_links):,}, Committees {len(committees):,}")

    # Check the ID assumption: CanElections.CandidateID and CmteCandidateLinks.CandidateID
    # are Candidates.ID (the data dictionary's wording is unclear). Print how many resolve.
    candidate_ids = set(isbe_candidates["ID"])
    for label, frame in (("CanElections", isbe_elections), ("CmteCandidateLinks", isbe_links)):
        resolved = frame["CandidateID"].isin(candidate_ids).mean()
        print(f"  {label}.CandidateID found in Candidates.ID: {resolved:.1%}")

    # ISBE candidate records for Chicago offices only: district text says Chicago,
    # or district is a bare number and the address city is Chicago.
    named_district = isbe_candidates["District"].str.match(CHICAGO_DISTRICT_PATTERN)
    bare_district = (
        isbe_candidates["District"].str.match(BARE_NUMBER_DISTRICT_PATTERN)
        & isbe_candidates["City"].str.strip().str.lower().isin(BARE_NUMBER_DISTRICT_ADDRESS_CITIES)
    )
    bare_district_no_address = (
        isbe_candidates["District"].str.match(BARE_NUMBER_DISTRICT_PATTERN)
        & (isbe_candidates["City"].str.strip() == "")
        & BARE_NUMBER_DISTRICT_NO_ADDRESS_COUNTS
    )
    isbe_candidates["is_chicago"] = named_district | bare_district | bare_district_no_address
    isbe_candidates["district_basis"] = ""
    isbe_candidates.loc[named_district, "district_basis"] = "district_text_chicago"
    isbe_candidates.loc[bare_district, "district_basis"] = "bare_number_and_chicago_address"
    isbe_candidates.loc[bare_district_no_address, "district_basis"] = BARE_NUMBER_NO_ADDRESS_BASIS
    isbe_candidates["district_number"] = (
        isbe_candidates["District"].str.extract(CHICAGO_DISTRICT_PATTERN)[0]
        .fillna(isbe_candidates["District"].str.extract(BARE_NUMBER_DISTRICT_PATTERN)[0])
        .fillna("")
    )
    print(f"  Chicago records by district basis: {isbe_candidates['district_basis'].value_counts().to_dict()}")
    chicago = isbe_candidates[isbe_candidates["is_chicago"]].copy()
    chicago["last_name_words"] = chicago["LastName"].map(lambda text: normalize_name(text).split())
    chicago["first_word"] = chicago["FirstName"].map(lambda text: (normalize_name(text).split() or [""])[0])
    print(f"ISBE candidate records with a Chicago district: {len(chicago):,}")

    elections_by_candidate = defaultdict(list)
    for row in isbe_elections.itertuples():
        elections_by_candidate[row.CandidateID].append(f"{row.ElectionYear} {row.ElectionType}")
    links_by_candidate = defaultdict(list)
    candidates_by_committee = defaultdict(list)
    for row in isbe_links.itertuples():
        links_by_candidate[row.CandidateID].append(row.CommitteeID)
        candidates_by_committee[row.CommitteeID].append(row.CandidateID)
    committee_by_id = committees.set_index("ID").to_dict("index")
    committees["name_words"] = committees["Name"].map(lambda text: normalize_name(text).split())
    searchable_committees = committees[committees["Status"].isin(NAME_SEARCH_COMMITTEE_STATUSES)]

    def committee_columns(committee_id):
        committee = committee_by_id.get(committee_id, {})
        return {
            "committee_id": committee_id,
            "committee_name": committee.get("Name", "(not in Committees.txt)"),
            "committee_type": committee.get("TypeOfCommittee", ""),
            "committee_status": committee.get("Status", ""),
            "committee_status_date": committee.get("StatusDate", ""),
            "committee_creation_date": committee.get("CreationDate", ""),
            "candidates_linked_to_committee": "; ".join(sorted(set(candidates_by_committee.get(committee_id, [])))),
        }

    output_rows = []
    steps_on = normalization_steps_on()
    for candidate in candidates.itertuples():
        cboe_words = normalize_name(candidate.ballot_name_raw).split()
        base = {
            "candidate_id": candidate.candidate_id,
            "office_code": candidate.office_code,
            "district_number": candidate.district_number,
            "ballot_name_raw": candidate.ballot_name_raw,
            "also_filed_as": candidate.also_filed_as,
            "normalization_steps_on": steps_on,
        }
        candidate_rows = []

        # 1. ISBE candidate records + their official committee links.
        office_values = ISBE_OFFICES_BY_CBOE_CODE[candidate.office_code]
        same_office = chicago[chicago["Office"].isin(office_values)]
        for isbe_row in same_office.itertuples():
            match_type = last_name_match_type(isbe_row.last_name_words, cboe_words)
            if match_type is None:
                continue
            elections = sorted(elections_by_candidate.get(isbe_row.ID, []), reverse=True)
            isbe_columns = {
                "isbe_candidate_id": isbe_row.ID,
                "isbe_last_name": isbe_row.LastName,
                "isbe_first_name": isbe_row.FirstName,
                "isbe_office": isbe_row.Office,
                "isbe_district_raw": isbe_row.District,
                "isbe_district_number": isbe_row.district_number,
                "isbe_district_basis": isbe_row.district_basis,
                "last_name_match_type": match_type,
                "district_matches": isbe_row.district_number == candidate.district_number,
                "first_word_matches": bool(cboe_words) and isbe_row.first_word == cboe_words[0],
                # Jr / Sr / II / III / IV written in each name (dropped by normalization).
                "suffix_matches": name_suffixes(isbe_row.LastName + " " + isbe_row.FirstName)
                                  == name_suffixes(candidate.ballot_name_raw),
                "isbe_election_records": "; ".join(elections),
                f"has_{ELECTION_YEAR}_election_record": any(e.startswith(ELECTION_YEAR) for e in elections),
            }
            committee_ids = links_by_candidate.get(isbe_row.ID, [])
            if not committee_ids:
                candidate_rows.append({**base, "evidence_source": "isbe_candidate_no_committee_link", **isbe_columns})
            for committee_id in sorted(set(committee_ids)):
                candidate_rows.append({**base, "evidence_source": "cmte_candidate_link",
                                       **isbe_columns, **committee_columns(committee_id)})

        # 2. Committees named with both the first and last word of the ballot name.
        if len(cboe_words) >= 2:
            first_word, last_word = cboe_words[0], cboe_words[-1]
            for committee in searchable_committees.itertuples():
                if (committee_name_has_word(committee.name_words, first_word)
                        and committee_name_has_word(committee.name_words, last_word)):
                    candidate_rows.append({**base, "evidence_source": "committee_name_contains",
                                           **committee_columns(committee.ID)})

        if not candidate_rows:
            candidate_rows.append({**base, "evidence_source": "none"})
        output_rows.extend(candidate_rows)

    PROPOSALS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROPOSALS_OUTPUT_PATH, "w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    proposals = pd.DataFrame(output_rows)
    per_candidate = proposals.groupby("candidate_id")["evidence_source"].agg(set)
    print(f"\n{len(proposals):,} proposal rows for {len(candidates)} candidates")
    print("candidates with at least one row of each kind:")
    for source in ("cmte_candidate_link", "isbe_candidate_no_committee_link", "committee_name_contains", "none"):
        print(f"  {source}: {sum(source in sources for sources in per_candidate)}")
    print(f"wrote {PROPOSALS_OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
