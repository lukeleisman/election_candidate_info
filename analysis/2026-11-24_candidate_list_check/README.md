# Candidate-list check: tests, 2026-11-24

scripts/check_candidate_list.py (make candidate-list-check, part of make candidates) was tested on the real
11/9/2026 CBOE list with edited copies of its text lines (outputs went to a throwaway folder; real files untouched):
- (a) Joe Holberg's line deleted -> MAYOR-00-014 not_on_list, flag removed_from_list, greyed out.
- (b) "JOE HOLBERG Removed" (unknown status word) -> unreadable_line flag + missing_in_race_with_unreadable_line;
      needs_review, NOT greyed out (rule tightened after the first test greyed him out).
- (c) "JANE NEWNAME Candidate" added under Mayor -> on_list_not_in_our_table flag; nothing greyed out.
Page check (port 8766): candidate_list_check.csv temporarily edited to mark MAYOR-00-014 not_on_list ->
greyout_test_holberg_TEST_ONLY.jpg (Summary table; tag found in 6 places; row opacity 0.5). Real file restored and
the page rebuilt afterwards (no "TEST ONLY" text in data/candidates or docs/data).
Live run 2026-11-24 18:43 UTC: all 6 CBOE documents unchanged (Last-Modified re-check), 250 on list, 3 name flags.
