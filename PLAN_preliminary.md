# Chicago election candidate info — Phase 1 plan

## Context
`election_candidate_info/` is empty (not yet a git repo). Goal: a public repo collecting endorsements,
funding, field activity (door knocking), platforms, and filed-form links for Chicago candidates,
starting with the **Feb 23, 2027 aldermanic election**. Key dates (Chicago Board of Elections,
verified 2026-10-04): petition filing Oct 19–26, 2026; objections Oct 27–Nov 2; election Feb 23, 2027.
The official candidate list does not exist yet — the user will **paste** a table of declared candidates.

Agreed **Phase 1** scope: repo skeleton + pasted candidate table + campaign finance from **both** ISBE
bulk files and Illinois Sunshine (side by side, never auto-chosen) + a candidate→committee crosswalk the
user confirms by hand + finance tables + written inventories of data sources and prior work.
Phase 2: endorsements, door knocking (self-reported counts first, then canvass events, then field
expenditures), platforms.

Conventions mirror sibling repo `../chicago_council/` (conda `environment.yml`, `scripts/`, `notebooks/`,
`sessions/`, `data/raw/` gitignored, fetch scripts with every choice as a named constant at the top and a
manifest of URLs + retrieval times — pattern from `../chicago_council/scripts/fetch_elms.py`).

## What research found (2026-10-04)

### Finance sources
- **ISBE bulk files** `https://www.elections.il.gov/CampaignDisclosureDataFiles/` — verified. Tab-delimited,
  refreshed daily (Receipts.txt ~1.06 GB, last-modified today). WebFetch → 403; `curl` with a browser
  User-Agent → 200. Files: Candidates, CanElections, CmteCandidateLinks, Committees, D2Totals,
  Expenditures, FiledDocs, Receipts, Officers, Investments, data dictionary.
  - `Candidates.Office`/`District` (ward #) + `CmteCandidateLinks` = the official candidate↔committee link.
  - `D2Totals`: per-report totals incl. itemized vs **not-itemized** individual contributions, cash, debts.
  - `Receipts`: itemized donor rows; `Archived` flags superseded amendments; `D2Part` separates
    individual contributions / transfers / loans / other / in-kind.
  - `Expenditures` D2Part=9: independent expenditures with `CandidateName`/`Office`/support/oppose.
  - `FiledDocs`: every report (D-1, Quarterly, A-1 …) → "links to filed forms".
- **Illinois Sunshine** (Reform for Illinois; originally DataMade) — derived from ISBE data. Code:
  `datamade/illinois-sunshine` (archived 2016, last DataMade push 2016; site still run by Reform for
  Illinois). JSON/CSV API endpoints from that code and from a Feb-2026 student script
  (`uchicago-2026-capp30122/project-il-legible`) that used it successfully:
  `/api/advanced-search/?term=&table_name=candidates`, `/api/committees/`,
  `/api/receipts/?committee_id=…&received_date__ge=…&datatype=csv`, `/api/expenditures/`,
  `/api/elections/`, `/api/top-money/`.
  **Today the site returned 502 then timed out** (two tries) — reliability is an open question.
- **Chicago Data Portal lobbyist data** (Board of Ethics), updated daily: `p9p7-vfqc` Lobbyist
  Contributions (lobbyist → candidate donations), `tq3e-t5yq` Lobbyists, `g8p5-y4m5` Clients,
  `pahz-egmi` Lobbying Activity. Useful to flag lobbyist money per candidate.

### Prior work to pull from (GitHub / web)
- `southsideweekly/ald_finance` (R, 2019): aldermanic receipts via Sunshine `/api/receipts/` by
  committee ID; committee IDs came from **The Daily Line's aldermanic spreadsheet**; cycle start =
  "day after last municipal election"; donor name/org cleaning + industry coding. Mirror its query shape.
- `shu1513/electionssimplified` `docs/plans/plan-illinois-local-finance.md` (active, 2026-07): an
  ISBE-bulk finance pipeline whose audit lists pitfalls we should avoid from day one:
  committee matching by name guess (use `CmteCandidateLinks` instead); itemized sums mislabeled as
  total receipts (use D-2); mixing transfers/loans/in-kind into "contributions"; double counting
  transfers between a candidate's own committees; approximate cycle windows. Cite it in code comments.
- `chielections.com` (independent, 2026): "Council 2027 ward guide & tracker" — every ward's incumbent +
  known challengers + endorsements (updated 2026-09-11) and rolling council-race digests. Good
  cross-check for the pasted candidate list and a Phase-2 endorsement lead (check terms before reuse).
- `publicgoodpolicy/chi-council-votes` (council vote tracker), `City-Bureau/aldermanic-menu-money` —
  adjacent; note only.
- Block Club 2023 "search every donation to aldermanic candidates" tool — a model for output.
- Other repos found are stale forks of Illinois Sunshine (`eads/`, `rockandrolla13/`, `uchicagotechteam/`).

### Candidate lists / forms
Chicago BOE publishes a candidate-list PDF after filing (expected after Oct 26), petition copies on
request, and an Electoral Board decisions library (.xlsx). Ballotpedia / Wikipedia as cross-checks.
Cook County Clerk Statements of Economic Interests — not yet checked.

## Repo layout
```
README.md  environment.yml  .gitignore
docs/sources.md          data-source inventory (URL, provides, access, verified?, phase)
docs/prior_work.md       repos/projects above: what each does, what we reuse, license
docs/finance_definitions.md   every finance metric: formula, source columns, caveats
data/input/aldermanic_candidates_2027.csv      pasted table, verbatim (committed)
data/crosswalk/candidate_committee_proposals.csv   generated evidence, all possible matches
data/crosswalk/candidate_committee.csv         user-confirmed CommitteeIDs (committed)
data/raw/isbe/  data/raw/sunshine/  data/raw/chicago_portal/   (gitignored, each with manifest.json)
data/tables/             committed aggregate outputs
scripts/fetch_isbe.py  scripts/fetch_sunshine.py  scripts/fetch_lobbyist_contributions.py
scripts/propose_committee_matches.py  scripts/build_finance_tables.py
notebooks/finance_review.ipynb  notebooks/isbe_vs_sunshine.ipynb
sessions/2026-10-04.md
```
`git init` locally; no remote / push until the user says so.

## Steps
1. **Skeleton** + `environment.yml` modeled on `../chicago_council/environment.yml` (no geo stack;
   add `requests`). README with provenance.
2. **Candidate table**: save the paste verbatim; any added key column only with user OK.
3. **`fetch_isbe.py`**: download ISBE files; manifest (URL, Last-Modified, retrieved-at, bytes, rows).
   Constants: `ISBE_BASE_URL`, `FILES_TO_FETCH`, `USER_AGENT`, `SECONDS_BETWEEN_REQUESTS`.
4. **`fetch_sunshine.py`**: for each confirmed committee ID, pull Sunshine committee + receipts +
   expenditures JSON/CSV verbatim. Constants: `SUNSHINE_API_BASE`, `RECEIPTS_START_DATE`, pause,
   timeout, `STOP_ON_HTTP_STATUS`. Records failures in the manifest instead of retrying blindly.
   (Also used for candidate search as extra evidence in step 6.)
5. **`fetch_lobbyist_contributions.py`**: Socrata pull of `p9p7-vfqc`, raw.
6. **`propose_committee_matches.py`**: per pasted candidate, list **every** ISBE candidate record +
   linked committees that could match (official `CmteCandidateLinks` link, office text, ward, last/first
   name, committee status/creation date) and Sunshine search hits. Writes evidence; **never picks**.
   User copies confirmed IDs to `candidate_committee.csv` (multiple committees allowed, with a
   `committee_role` column the user fills: candidate committee / ward org / other).
   Constant `OFFICE_TEXT_PATTERNS` shown and editable.
7. **`build_finance_tables.py`** (confirmed crosswalk only). Every choice below is a named constant in a
   `FINANCE_CHOICES` block at the top, each with an `# OPEN QUESTION` comment until the user sets it:
   - `CYCLE_START_DATE` — options: 2023-04-05 (day after 2023 runoff, SSW convention) / 2023-03-01 /
     committee creation date.
   - `DONOR_IDENTITY_RULES` — itemized donors only (IL itemizes > $150 aggregate); outputs a donor count
     **per rule** side by side: exact (last, first, zip) / (last, first) / (last, first, address1).
   - `A1_HANDLING` — whether A-1 receipts reappear on the next quarterly; report A-1 separately until
     verified against FiledDocs on real committees.
   - `MULTI_COMMITTEE_TRANSFERS` — show per-committee and summed; flag transfers between a candidate's
     own committees rather than netting silently.
   - `INCLUDE_RECEIPT_PARTS` — which D2Part codes count as "contributions" (default: 1 only; others shown
     in their own columns).
   Outputs (`data/tables/`):
   - `finance_reports.csv` — every non-archived D-2 per committee, all D2Totals columns (raw layer).
   - `finance_summary_isbe.csv` — per candidate: cash on hand (latest D-2), receipts since cycle start
     split by D2 part, itemized vs not-itemized individual $, A-1 since last quarterly, donor counts per
     rule, independent expenditures support/oppose, lobbyist contributions (from portal).
   - `finance_summary_sunshine.csv` — same metrics computed from Sunshine pulls.
   - `finance_source_comparison.csv` — ISBE vs Sunshine per metric per candidate with difference column
     (no reconciliation picked automatically).
   - `filed_documents.csv` — every filed doc per committee (+ ISBE link once URL format verified).
   - Donor-level rows stay in `data/raw/` (not committed) pending the open question below.
8. **Notebooks**: `finance_review` shows raw rows behind each number; `isbe_vs_sunshine` shows where the
   two sources differ and why.
9. **Docs**: `sources.md` (incl. Phase-2 endorsement/platform/door-knock sources: UWF, CTU, CFL, SEIU
   HCII, Chicago DSA, IVI-IPO, Sierra Club IL, PP IL Action, Equality IL, FOP, Better Streets, Sun-Times /
   Tribune editorial boards, chielections; questionnaires from Sun-Times, WTTW, Better Streets, Block
   Club; Mobilize.us public events; field-expenditure keywords), `prior_work.md`,
   `finance_definitions.md`.

## OPEN QUESTIONS (recorded in code/docs, not silently resolved)
- The `FINANCE_CHOICES` values above (cycle start, donor identity, A-1, transfers, receipt parts).
- Publishing donor-level rows (names/addresses are public at ISBE) in a public repo — default: no.
- ISBE filed-document URL format for direct links — verify.
- Illinois Sunshine availability (502/timeouts today) and how fresh its ISBE copy is — measure via
  comparison table; if down, ISBE-only output still works.
- Licensing/permission before reusing chielections.com or Daily Line content.

## Verification
- Fetch scripts: files + manifests present, row counts printed.
- Proposals CSV: every pasted candidate appears with 0+ candidate matches and evidence columns.
- For 3–5 incumbents: compare cash on hand and quarterly receipts against ISBE's committee web page and
  Illinois Sunshine's page; explain differences in the session log.
- Both notebooks run top to bottom.
