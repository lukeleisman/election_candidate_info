# Process: reviewing candidate → committee judgment calls

Who: you, or a Claude agent session given this file. Output goes in
`data/crosswalk/candidate_committee_review.csv`; nothing else is edited by hand.

## How the pipeline gets here
```
make committee-proposals   # every committee that could belong to each candidate (evidence)
make committee-review      # review sheet; keeps earlier marks
make review-rule           # scripts/apply_review_rule.py marks clear cases (reviewed_by = rule_v1)
make apply-review          # candidate_committee.csv <- rows with accept = yes
```
Only rows marked `yes` count toward a candidate's money. Blank rows count for nothing,
so an unreviewed judgment call **leaves money out** rather than adding wrong money.

## What to review
Filter the sheet to `rule_outcome = judgment_call` (and `accept` blank). `rule_reason` says why:

| rule_reason | What it means | What to decide |
|---|---|---|
| `multiple_strong_rows` | Candidate has 2+ active committees ISBE links to them, first name matching | Which are theirs. Often: own committee **yes**; a ward organization or PAC linked to them → yes only if you want its money counted for the candidate, role `ward organization` / `other` |
| `closed_in_cycle` | Their committee closed (F) after 2023-04-05 | **yes** if it raised money for this run before closing (e.g. replaced by a new committee); role `candidate committee`. Finance code will apply the cycle start date |
| `name_only_evidence` | No ISBE link; committee name contains their first + last name | Open the ISBE committee page; **yes** if the committee is for this person and this race |
| `not_candidate_type` | Would be auto-accepted, but ISBE type is e.g. Political Action | PACs (e.g. "Chicago Aldermanic Black Caucus PAC") → usually **no**. Police District Council **slate** committees → see open question below |
| `suffix_differs` | ISBE name has a different Jr / Sr / II / III than the ballot name | Possibly a parent/child with the same name (27th Ward: Walter Burnett, Jr vs his son Walter "Red" Burnett). **no** if it is the other person; **yes** if the ballot just omits the suffix |
| `shared_with_other_candidate` | Same committee would go to 2+ candidates | Ward 24 Scott / Ward 39 Nugent: both CBOE filings map to one ISBE record — decide which filing is the committee's candidate; mark the other **no** and say why in `review_notes` |

Also worth a look (rule decided, but check later): `rule_reason = single_strong_row`
rows (accepted) — skim committee names for anything that isn't the candidate's own
campaign.

## How to mark a row
- `accept`: `yes` or `no`
- `committee_role`: `candidate committee` / `ward organization` / `slate committee` / `other`
- `reviewed_by`: your initials, or `agent_YYYY-MM-DD` for an agent session
- `review_notes`: the evidence used — **a URL or the ISBE committee ID page checked**, one line

Agent sessions: do not mark anything `yes` without writing the evidence in `review_notes`.
Leave a row blank if unsure; blank is safe.

Where to check a committee: ISBE committee search
https://www.elections.il.gov/CampaignDisclosure/CommitteeSearch.aspx (committee ID →
officers, reports filed, candidate listed on the D-1).

## Prompt for an agent session
> Read `docs/process_committee_review.md`. In `data/crosswalk/candidate_committee_review.csv`,
> review the rows with `rule_outcome = judgment_call` and blank `accept`, for reasons: <list>.
> Mark each as described, with `reviewed_by = agent_<today>` and evidence in `review_notes`.
> Do not change any other row. Then run `make apply-review` and report the warnings it prints.

## OPEN QUESTIONS (yours to decide — do not resolve in review)
- **Slate committees** (Police District Council): e.g. "DC 20 Alliance" (Faulkner, Kling, Smith),
  "Rochford, Levy & Lindley for 17". Count the whole committee for each candidate (double-counts
  across the slate), split it evenly, or report slate money separately? Until decided, mark
  these `yes` with role `slate committee` only if you want them included at all; the finance
  scripts will report slate committees in their own columns, not add them in.
- **Ward organizations / allied PACs** linked to a candidate: counted as the candidate's money
  or shown separately? (Mirrors `MULTI_COMMITTEE_TRANSFERS` in `PLAN_preliminary.md`.)
