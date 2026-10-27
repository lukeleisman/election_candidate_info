# Plan v2 — Chicago 2027 candidate info: official list, money, donor mix, endorsements

## Context
`PLAN_preliminary.md` (2026-10-04) was written before filing closed. Three things changed:
1. **The candidate list is set.** CBOE published an official *Candidate Filing Report*
   (`https://cboeprod.blob.core.usgovcloudapi.net/prod/2026-10/Candidate Filing Report_20261026174516936.pdf`,
   printed 10/26/2026 5:45 PM, 20 pages, footer `*** CANDIDATE TOTAL: 256 ***`, 53 offices: Mayor, Clerk,
   Treasurer, 50 wards). Verified today: it downloads with a browser User-Agent and pdfplumber extracts
   it cleanly (columns: Filing Date+time, Office/District, Filing #, Candidate, Mailing Address, City, Zip;
   long names and addresses wrap onto a second line, e.g. "DANIELLE CARTER- / WALTERS"). The Notion /
   Bluesky / pasted lists in `data/input/` become cross-checks, not the source of truth.
   Objections run Oct 27–Nov 2, so ballot status will still change → track it.
2. **Everything must be rerunnable code or a written, repeatable process** — not ad-hoc agent web searches.
3. **Key questions first:** who endorses each candidate; how much money; how diverse that money is
   (individuals vs. organizations / committees / lobbyists; small vs. large donors).

User decisions (2026-10-27): cover **all offices** in the report; candidate **addresses stay in
`data/raw/` only**; endorsements via **snapshot + per-source parsers**, with an *optional* **local open
LLM** extraction step, a **manual-entry CSV**, and a documented **Claude-agent research process** whose
output lands in that same CSV for review.

Other status checked today: Illinois Sunshine home page is up (200) but `/api/committees/` and
`/api/advanced-search/` return its "Error!" HTML page → still unreliable; ISBE bulk files still fine.

Found while building step 2 (2026-10-27): the report's "Council Member, Chicago Police Department"
rows are the **Police District Council** races (95 candidates, all 22 police districts) — included,
office code `PDC`. Totals: Mayor 16, Clerk 1, Treasurer 2, Alderperson 142 (50 wards), PDC 95.

Everything from `PLAN_preliminary.md` (ISBE fetch, Sunshine side by side, crosswalk the user confirms,
`FINANCE_CHOICES` open questions, lobbyist portal data, conventions from `../chicago_council/`) carries
forward unless changed below.

## Repo layout (additions/changes vs. preliminary plan in **bold**)
```
PLAN.md                      **replaces PLAN_preliminary.md (kept, marked superseded)**
Makefile                     **one target per step + `make all`; the rerun entry point**
environment.yml              conda env `election-candidate-info` (pandas, requests, **pdfplumber**,
                             **openpyxl**, **beautifulsoup4**, jupyter, nbstripout; **ollama python client optional**)
config/endorsement_sources.csv   **user-curated registry of endorsing orgs (see §4)**
data/raw/cboe/  data/raw/isbe/  data/raw/sunshine/  data/raw/chicago_portal/  **data/raw/endorsements/**
                             (all gitignored; each has manifest.json: URL, retrieved_at, bytes, sha256, HTTP status)
data/candidates/candidates_cboe.csv          **parsed official list, committed (no addresses)**
data/candidates/candidate_list_comparison.csv  **CBOE vs Notion/Bluesky/pasted lists**
data/candidates/ballot_status.csv            **objection / Electoral Board outcomes per candidate**
data/crosswalk/candidate_committee_proposals.csv  data/crosswalk/candidate_committee.csv
**data/crosswalk/candidate_isbe_review.csv  committee_additions_manual.csv  committee_groups.csv  (§3a)**
data/endorsements/endorsements_manual.csv   **hand / agent-entered rows**
data/endorsements/endorsements_extracted.csv **parser + LLM output, with review status**
data/endorsements/endorsements.csv          **reviewed, matched to candidate_id**
data/tables/   finance + donor-mix + endorsement summary tables
scripts/  notebooks/  docs/  sessions/
```

## Steps

### 1. Skeleton
`environment.yml` (mirror `../chicago_council/environment.yml`, drop geo stack), `.gitignore`
(`data/raw/`), `Makefile`, README update, rename plan → `PLAN.md`.

### 2. Official candidate list (code, rerunnable)
- **`scripts/fetch_cboe.py`** — GET `CBOE_CANDIDATES_PAGE = https://chicagoelections.gov/getting-ballot/candidates`,
  save the HTML, download every link whose text/URL matches `CBOE_DOCUMENT_PATTERNS`
  (`Candidate Filing Report`, `Candidate List`, `Electoral Board Decisions`, `Ballot Placement Lottery`).
  Never overwrites: files saved under their original name (CBOE names include a timestamp), so later
  updated reports accumulate and can be diffed. Constants: `USER_AGENT`, `SECONDS_BETWEEN_REQUESTS`.
- **`scripts/parse_cboe_filing_report.py <pdf>`** — pdfplumber word positions → columns using
  `COLUMN_X_BOUNDARIES` (named constants read off the header row, printed when run so you can check).
  A row starts at a `MM/DD/YY` date in column 1; following lines with no date are continuations
  (time, wrapped name, wrapped address). Office carries down until a new office appears.
  **Validation (fails loudly):** row count == the `CANDIDATE TOTAL` line; every ward 1–50 present;
  no blank names. Output `candidates_cboe.csv`: `candidate_id, office, ward, filing_datetime,
  filing_number, ballot_name_raw, source_pdf, source_page`.
  Raw addresses → `data/raw/cboe/candidates_with_addresses.csv` only.
  - `candidate_id` (new key column — approve with this plan): `<office_code>-<ward 2-digit>-<filing order within office>`,
    e.g. `ALD-01-003`, `MAYOR-00-005`. **OPEN QUESTION:** filing order can change if a later report
    reorders; alternative is a name-based slug. Script prints both so you can pick before anything depends on it.
- **`scripts/compare_candidate_lists.py`** — joins CBOE to `candidates_2026-10-26_notion.csv`,
  `..._bluesky.csv`, `aldermanic_candidates_2027.csv` by (office, ward, normalized name).
  `NAME_NORMALIZATION_STEPS` listed as constants (uppercase, strip punctuation/quotes, collapse spaces,
  drop nickname in quotes/parens — each step a separate toggle). Output shows in-CBOE-only /
  in-list-only / matched, plus the normalized strings used. No fuzzy matching auto-accepted;
  near-misses listed in a separate column with edit distance for you to judge.
- **`scripts/build_ballot_status.py`** — from the Electoral Board decisions xlsx (2027 edition, once
  posted) and later certified lists: per candidate, objection filed / decision / on ballot. Until
  the 2027 file exists the script reports "not yet published" rather than guessing.

### 3. Money and donor mix (extends preliminary steps 3–8)
Preliminary plan steps 3–7 unchanged (ISBE fetch, Sunshine fetch with failure recording, lobbyist
portal pull, `propose_committee_matches.py` now driven by `candidates_cboe.csv` for all offices,
`build_finance_tables.py` with `FINANCE_CHOICES`).

#### 3a. Candidate → committee crosswalk — revised 2026-10-27 (Illinois Sunshine model, extended)
**Why revised:** the first version reviewed every candidate × committee pair (327 rows, 90 judgment
calls). Illinois Sunshine (DataMade, `github.com/datamade/illinois-sunshine`, `etl.py`
`SunshineCandidateCommittees` + `candidate_money` view) does no committee-level judging: it loads ISBE
`CmteCandidateLinks.txt` as published and shows every linked committee as its own row with its own
total. It can do that because it starts from ISBE candidate records; we start from the CBOE ballot, so
our one real matching problem is **CBOE candidate → ISBE candidate record**. User decision
(2026-10-27): adopt Sunshine's approach, and improve on it by (1) also tracking committees ISBE does
not link, and (2) offering named options for adding committees together.

Three layers, each a separate file:
1. **Candidate → ISBE record (reviewed).** `data/crosswalk/candidate_isbe_review.csv`, one row per
   CBOE candidate × ISBE candidate record with a matching last name (345 pairs on 2026-10-27; 181 of
   256 candidates have ≥1, 75 have none). Evidence columns as now (district, first word, suffix,
   election records). Rule marks pairs where district + first word + suffix all match (129 pairs /
   124 candidates on 2026-10-27; thresholds as named constants); the rest are judgment calls. This is
   where the hard cases now live: Burnett Jr vs son, the duplicate Scott / Nugent filings, and
   people with several ISBE records. Existing marks carry over: an ISBE record with any `yes`
   committee row → `yes`; the user's `no` rows (Burnett Jr) → `no`.
2. **Committees (automatic, not reviewed).** `data/crosswalk/candidate_committee.csv`, one row per
   candidate × committee, column `link_basis`:
   - `isbe_link` — every `CmteCandidateLinks` committee of an accepted ISBE record, any type or
     status (Sunshine's rule, unchanged).
   - `name_only` — committee name contains the candidate's first + last word, no ISBE link to them
     (18 rows / 15 candidates on 2026-10-27). Listed so nothing ISBE missed is invisible; flagged.
   - `manual` — from `data/crosswalk/committee_additions_manual.csv` (hand / agent-entered, with
     source URL): committees found elsewhere (news, candidate site, A-1s). Also holds `exclude` rows
     if a link is plainly wrong — the exclusion is a visible row, never a silent drop.
   Every row carries ISBE committee type, status, status date, creation date, and the other
   candidates linked to the same committee (slates).
3. **Combining committees (a finance choice, not a crosswalk choice).** Finance tables always show
   one row per committee first. Candidate totals are computed **side by side** under each named
   option in `COMMITTEE_COMBINATION_OPTIONS` (in `build_finance_tables.py`), never one chosen, e.g.:
   - `isbe_linked_candidate_type` — `isbe_link` rows whose ISBE type is Candidate
   - `isbe_linked_all` — every `isbe_link` row (Sunshine's view)
   - `isbe_linked_plus_name_only` — adds `name_only` rows
   - `manual_groups` — combinations you list in `data/crosswalk/committee_groups.csv`
     (candidate_id, group name, committee IDs, why) — for "add these together when appropriate"
   Transfers between committees added together are flagged and shown, not netted
   (`MULTI_COMMITTEE_TRANSFERS`). Slate committees (one committee, several candidates) are marked in
   every option; how they are counted is an OPEN QUESTION below.

Replaces: `build_committee_review.py` / `apply_review_rule.py` / `apply_committee_review.py` work on
candidate × ISBE record instead of candidate × committee; `docs/process_committee_review.md` is
rewritten for that. `candidate_committee_review.csv` was checked against the new crosswalk
(2026-10-27: all 99 old accepts present, or Police District Council, or in the new judgment calls)
and removed; it remains in git history. Duplicate filings (one person filed twice) are merged
through hand-entered `data/candidates/duplicate_filings.csv` (Scott 24, Nugent 39, Perez PDC 2).

User decisions (2026-10-27), superseding the options above where they differ:
- **Police District Councils skipped for now** in the committee step (`COMMITTEE_STEP_OFFICE_CODES`).
- Step-1 rule (`rule_v2`): all of district + first name + suffix match → yes; district **and** first
  name both differ → no; everything else a judgment call.
- **Slate / shared committees** → own column, not added in (`counts_toward = slate_column`: any
  committee in the crosswalk for 2+ candidates — this also catches ISBE links like the Aldermanic
  Black Caucus PAC, linked to 11 aldermen, and JCUA Votes).
- **`name_only` rows appear in the public table.**
- **Totals: each committee shown separately + one sum of everything else** (`candidate_sum`).
  No other combination options until needed; `committee_groups.csv` not built yet.
- **PACs / closed committees:** no rule now — decide after seeing them.
- General: **default to Illinois Sunshine when in doubt**; spend effort on what it misses and on
  bulk work. Endorsements (§4) are the bigger new piece.

**New: `scripts/build_donor_mix.py`** — per
candidate (confirmed committees only), every rule computed **side by side**, never one chosen:
- From **D2Totals** (covers non-itemized money): individual itemized $, individual **not-itemized** $
  (≤$150 — small-dollar proxy), transfers in $, loans $, other $, in-kind $, each as $ and % of total.
- From **Receipts** (itemized rows, `Archived` excluded, cycle window from `FINANCE_CHOICES`), each
  receipt tagged by rules in a `DONOR_TYPE_RULES` table at the top of the file:
  - `person`: D2Part 1 and `FirstName` non-blank
  - `organization`: D2Part 1 and `FirstName` blank (businesses, unions, etc.)
  - `committee_transfer`: D2Part 2; donor name joined to ISBE `Committees.txt` to get committee type
    (PAC / party / ward org / candidate) — join is exact-name, unmatched shown as `unmatched`
  - `self_or_family_loan`: D2Part 3 (name compared to candidate name, flagged not netted)
  - `lobbyist`: donor matches Chicago portal `p9p7-vfqc` lobbyist names (overlay flag, not exclusive)
  - `employer/occupation` kept raw; any industry coding is a later, separate lookup table you curate.
- Concentration metrics: unique donors (per each `DONOR_IDENTITY_RULES` variant), share of $ from top 10
  donors, median and mean itemized gift, $ from in-Chicago vs out-of-state zip.
- Output `data/tables/donor_mix.csv` (one row per candidate × rule) + `notebooks/donor_mix_review.ipynb`
  showing the raw receipt rows behind each number.
- **OPEN QUESTIONS** (in code): does ISBE put business/union contributions in D2Part 1 or 4? (check
  blank-`FirstName` counts by D2Part on real data before trusting `organization`); how to treat
  contributions from a union's PAC vs the union itself; whether to publish donor-level rows (default no).

### 4. Endorsements (rerunnable pipeline + manual/agent lane)
- **`config/endorsement_sources.csv`** (you curate; I seed it from the preliminary list: UWF, CTU, CFL,
  SEIU HCII, Chicago DSA, IVI-IPO, Sierra Club IL, PP IL Action, Equality IL, FOP, Better Streets,
  Sun-Times / Tribune editorial boards, chielections.com, ward orgs, plus candidate campaign sites):
  `source_id, org_name, url, page_kind (html/pdf/image), parser (name or "manual"), verified_on, reuse_terms_checked, notes`.
- **`scripts/fetch_endorsement_pages.py`** — snapshots every registry URL into
  `data/raw/endorsements/<source_id>/<timestamp>.<ext>` + manifest with sha256; reports which pages
  changed since the last run (so reruns show new endorsements).
- **`scripts/endorsement_parsers/<source_id>.py`** — one small parser per structured page
  (BeautifulSoup selectors as constants). Output rows: `source_id, endorser, candidate_name_raw,
  office_raw, ward_raw, quote, url, snapshot_file, retrieved_at, method=parser`.
- **`scripts/extract_endorsements_llm.py`** (optional, off unless you turn it on) — for snapshots with
  no parser, sends cleaned page text to a **local open model via Ollama**. Constants:
  `LLM_BACKEND = None` (options listed: `"ollama"`), `LLM_MODEL` (pinned tag, e.g. a Llama/Qwen
  instruct model — **OPEN QUESTION: which model; you pick**), `TEMPERATURE = 0`, the full prompt text,
  and a JSON schema. Every row must include a verbatim `quote`; the script drops any row whose quote
  is not found in the page text. Rows get `method=llm:<model>`, `review_status=unreviewed`.
- **`data/endorsements/endorsements_manual.csv`** — same columns + `entered_by` (`luke` /
  `claude_agent_<date>`), `review_status`. For press articles, social posts, images.
- **`docs/process_endorsement_research.md`** — the repeatable *agent* process: the exact prompt to
  give a Claude session ("for ward N / source S, find endorsements; for each give URL, verbatim quote,
  date; append to endorsements_manual.csv with entered_by=claude_agent_<date>, review_status=unreviewed;
  add new sources to the registry"), plus what to check when reviewing.
- **`scripts/match_endorsements.py`** — combines parser, LLM, and manual rows; matches to
  `candidate_id` with the same normalization steps as §2 (exact normalized match within office/ward
  only; others listed as needs-review). Output `endorsements.csv` (reviewed rows only feed tables) and
  `data/tables/endorsements_by_candidate.csv` (count + list of endorsers, by endorser type).

### 5. Candidate overview table
**`scripts/build_candidate_overview.py`** → `data/tables/candidate_overview.csv`: one row per
candidate, raw columns only — incumbent (from the pasted list's flag / council roster), ballot status,
committee found?, committee creation date, total receipts since cycle start, cash on hand, % from
individuals (each rule), unique donors, # reviewed endorsements. **No composite "seriousness" score**
— you decide whether one is wanted later.

### 6. Docs
`docs/sources.md` (add CBOE filing report, Electoral Board library, Ollama model), `docs/prior_work.md`,
`docs/finance_definitions.md` (+ donor-mix rules), `docs/process_endorsement_research.md`,
session log `sessions/2026-10-27.md`.

## Build order
1 → 2 (gets the official list committed today) → ISBE fetch + crosswalk proposals → **you confirm
committees** → finance + donor mix → endorsement registry + snapshots + manual CSV → parsers →
optional LLM step → overview table.

## Verification
- `make candidates`: parser asserts 256 rows == footer total, 50 wards present; spot-check 10 rows
  (incl. wrapped names) against the PDF; comparison table lists every Notion/Bluesky name as
  matched or unmatched.
- `make finance`: for 3–5 incumbents compare cash on hand and quarterly receipts with the ISBE
  committee page; D2Totals-based % sums to 100; Receipts-based person+organization $ for D2Part 1 is
  ≤ D2Totals itemized individual $ (difference shown).
- `make endorsements`: rerunning with no page changes produces identical output; LLM step drops
  rows whose quote is not in the text (test with one known page).
- `make all` runs top to bottom from a clean `data/raw/`; notebooks run with nbconvert.
