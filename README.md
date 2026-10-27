# Chicago election candidate info

This repository collects public information about candidates running for office in Chicago:
endorsements, campaign funding (amounts, number of donors, and where the money comes from),
field activity such as door knocking, stated platforms, and links to filed forms.

First target: the **February 23, 2027 municipal election** — Mayor, Clerk, Treasurer, all 50
aldermanic wards, and the Police District Councils. See `PLAN.md` for the plan.

## Status

- **Official candidate list — built.** Parsed from the Chicago Board of Elections *Candidate
  Filing Report* (2026-10-26, 256 candidates) → `data/candidates/candidates_cboe.csv`.
  Ballot status is tracked as Electoral Board objection cases are posted.
- **Candidate → committee crosswalk — built by rule** for 79 candidates; 104 judgment-call rows
  (72 candidates) await review per `docs/process_committee_review.md`.
- Campaign finance (Illinois State Board of Elections bulk files, Illinois Sunshine side by
  side), donor mix, endorsements — planned, see `PLAN.md`.

## Rerunning

Everything is rebuilt by scripts; nothing is edited by hand except the files marked as
hand-curated (`data/input/`, and later the committee crosswalk and endorsement entries).

```
conda env create -f environment.yml
make candidates            # fetch CBOE documents, parse the newest filing report, compare lists, ballot status
make fetch-isbe            # ISBE bulk files (~1.5 GB; skipped when unchanged on the server)
make committee-proposals   # ISBE records + linked committees + name matches (evidence)
make isbe-review           # review sheet: ballot candidate -> ISBE record (keeps your marks on rerun)
make isbe-rule             # marks clear cases by rule; judgment calls left blank
make candidate-committee   # crosswalk: every committee of a confirmed record (as on Illinois Sunshine) + name matches
```

Raw downloads go to `data/raw/` (gitignored), each with a `manifest.json` recording URL,
retrieval time, size and sha256.

## Data files

| File | What it is |
|---|---|
| `data/candidates/candidates_cboe.csv` | Official candidate list (no addresses) |
| `data/candidates/candidate_list_comparison.csv` | CBOE list vs. the unofficial lists in `data/input/` |
| `data/candidates/cboe_same_race_same_last_word.csv` | Same-race candidates sharing a last name, for review |
| `data/candidates/duplicate_filings.csv` | **Hand-entered:** one person filed twice; merged into the earlier filing in the committee step |
| `data/candidates/ballot_status.csv` | Electoral Board objection cases per candidate |
| `data/crosswalk/candidate_committee_proposals.csv` | Every ISBE committee that could belong to each candidate, with evidence (regenerated) |
| `data/crosswalk/candidate_isbe_review.csv` | **You edit this:** ballot candidate × ISBE candidate record, `accept` column (process: `docs/process_committee_review.md`) |
| `data/crosswalk/committee_additions_manual.csv` | **Hand-entered:** committees to add or exclude, with source URL |
| `data/crosswalk/candidate_committee.csv` | Candidate → committee rows (`link_basis`, `counts_toward`), rebuilt every run |
| `data/input/` | Unofficial lists pasted or transcribed by hand (kept verbatim) |
