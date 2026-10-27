# Process: confirming CBOE candidate → ISBE candidate record

Rewritten 2026-10-27 for the Illinois Sunshine model (PLAN.md §3a). The old per-committee
review (`candidate_committee_review.csv`, `rule_v1`) is retired.

## Why this is the only thing reviewed
CBOE (the ballot) and ISBE (campaign finance) share no ID. Illinois Sunshine starts from ISBE
records, so it never has to say "the person on the ballot is ISBE record X"; we start from the
ballot, so we do. Once a record is confirmed, **every committee ISBE links to it is included
automatically**, whatever its type or status, as on Sunshine. Committees whose name matches but
that ISBE doesn't link are added as `name_only`. Nobody reviews committees one by one. Whether
PACs or closed committees should count is decided later, after seeing them.

## Pipeline
```
make committee-proposals   # ISBE records with a matching last name, their committees, name matches
make isbe-review           # review sheet, one row per candidate x ISBE record; keeps earlier marks
make isbe-rule             # scripts/apply_isbe_record_rule.py marks clear cases (reviewed_by = rule_v2)
make candidate-committee   # data/crosswalk/candidate_committee.csv, rebuilt from the sheet
```
Hand-edited files: `data/crosswalk/candidate_isbe_review.csv` (accept / reviewed_by /
review_notes only), `data/crosswalk/committee_additions_manual.csv`,
`data/candidates/duplicate_filings.csv`. Everything else is generated.

Only rows marked `yes` bring in committees. Blank brings in nothing, so an unreviewed
row **leaves money out** rather than adding the wrong person's money. Blank is safe.

## What to review
Filter the sheet to `rule_outcome = judgment_call` with `accept` blank. `rule_reason` says why:

| rule_reason | What it means | Usually |
|---|---|---|
| `isbe_district_has_no_number` | First name + suffix match; ISBE district is just "Chicago" | **yes** if `linked_committees` look like this person's campaign for this race |
| `district_differs` | First name + suffix match; ISBE ward differs | Pre-2023 ward number (redistricting) → **yes** if it's the same person (incumbent, same committee name) |
| `first_name_differs` | Ward matches, first name doesn't | Nickname or spelling (Bill/William, Nate/Nathaniel, CBOE typo "LEOARDO") → **yes**. A different person with the same surname (a relative, a past candidate) → **no** |
| `suffix_differs` | Jr / Sr / II / III differs | Parent and child (Burnett Jr vs his son, already marked **no**) |
| `shared_with_other_candidate` | One ISBE record would go to 2+ candidates | Check `duplicate_filings.csv`; if it's one person filed twice, add a row there |

Columns that help: `isbe_first_name`, `isbe_district_raw`, `linked_committees` (ID, name,
status A/F, type), `isbe_election_records` (past races, e.g. "2023 CP"),
`has_2027_election_record`, `other_candidates_matching_record`.

## How to mark a row
- `accept`: `yes` or `no`
- `reviewed_by`: your initials + date, or `agent_YYYY-MM-DD` for an agent session
- `review_notes`: one line of evidence: what you compared, plus a URL if you looked something
  up. Saying what's in the sheet is enough when that decides it (e.g. "ISBE 'Bill' Morton, Ward 49,
  committee 'Friends of Bill Morton' — nickname of William").

Leave a row blank if unsure, and say why in `review_notes`.

Where to check when the sheet isn't enough: ISBE candidate / committee search,
https://www.elections.il.gov/CampaignDisclosure/CommitteeSearch.aspx (committee ID →
officers, address, D-1 candidate). Prefer this over news searches.

## Session instruction (paste into a new Claude Code session)
> Read `HANDOFF.md`, then `docs/process_committee_review.md`. In
> `data/crosswalk/candidate_isbe_review.csv`, review every row with
> `rule_outcome = judgment_call` and blank `accept`. Mark each one as the process doc says, with
> `reviewed_by = agent_<today's date>` and one line of evidence in `review_notes`. Change only
> `accept`, `reviewed_by` and `review_notes` on those rows. Don't change rows the rule or
> a person already marked, don't edit generated files, and don't add rows to
> `committee_additions_manual.csv` or `duplicate_filings.csv`. List anything you think belongs
> there in your report instead.
> Leave a row blank if the sheet and the ISBE site don't settle it.
> Then run `make isbe-review isbe-rule candidate-committee` and report:
> (1) a table of every row you marked (candidate, ISBE name, yes/no, one-line reason),
> (2) the rows you left blank and why, (3) the script output, including any WARNING lines,
> (4) any `name_only` committee in `candidate_committee.csv` that looks like it belongs to
> someone else. Don't commit; the user reviews first.

## OPEN QUESTIONS (the user's, not the reviewer's)
- PACs and closed committees that ISBE links to a confirmed record: count in the candidate's
  sum, or show separately? Decided after seeing them; for now they're in `candidate_sum`
  unless shared with another candidate (`slate_column`).
- Police District Council candidates are outside this step for now (`COMMITTEE_STEP_OFFICE_CODES`
  in `scripts/propose_committee_matches.py`).
