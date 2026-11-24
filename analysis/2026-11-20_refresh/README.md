# Money refresh, 2026-11-20

ISBE bulk files re-downloaded (`make fetch-isbe`, 27 min; Last-Modified Fri 20 Nov 2026 14:10-14:15 GMT),
then rebuilt without re-parsing the CBOE candidate list (candidate IDs untouched):
committee-proposals, isbe-review, isbe-rule, candidate-committee, finance, donor-mix, display-tables,
incumbents, candidate-links, dashboard.

Files here:
- `step_times.txt`  seconds per make target (input for plans/02 timings)
- `rebuild.log`     full make output
- `finance_summary_before.csv`  `git show 24566a6:data/tables/finance_summary.csv`
- `finance_summary_changes.csv` one row per (candidate, column) whose value changed; rebuilt by the
  inline pandas comparison of before vs data/tables/finance_summary.csv on these columns:
  cash_on_hand, since_2026_01_01_raised, a1_gifts_since_last_report,
  since_2026_01_01_raised_plus_a1_gifts, committees_summed, committees_with_no_d2_report.

Note: finance_reports.csv diffs mostly show RcvdDateTime losing its fractional seconds (ISBE's file format);
compare on the first 19 characters to see real changes.
