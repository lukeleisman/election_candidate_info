# Can the ISBE download be incremental? Probe, 2026-11-24

Question (user): `make fetch-isbe` takes 27 min (~1.28 GB, almost all Receipts.txt 1.07 GB). Can we fetch only updates?

Facts found (Receipts.txt; our copy = ISBE file of 2026-11-20, server file Last-Modified Tue 24 Nov 2026 14:15:56 GMT):
- Server answers byte-range requests (HTTP 206) and offers gzip (Content-Encoding: gzip on request).
- ISBE publishes only whole-database files; no "changes since" file was found.
- Rows are mostly, not strictly, in ID order: 149,887 of 6,590,304 rows have a lower ID than the row before.
- 2,000-byte samples at offsets 0, 300,000,000 and 800,000,000: identical to our Nov 20 copy.
- Binary search (18 range requests of 2,000 bytes, 1 s apart): first difference between bytes 1,041,222,986 and
  1,041,225,998, i.e. only the last ~24.2 MB of our copy differ. Our row at that point: ID 6580784,
  RcvDate 2026-02-20. Server file is 76,383 bytes longer (1,065,520,269 vs 1,065,443,886).
- So ISBE rewrites the recent end of the file (not append-only), and leaves the earlier ~98% byte-identical.

OPEN QUESTION: a same-length edit earlier in the file (e.g. a changed date) would not shift bytes and would not be
found by the binary search. Needs a check against a full download before trusting an incremental fetch.
Not yet probed: FiledDocs.txt (143 MB), D2Totals.txt (59 MB).

## Result (2026-11-24): incremental copies are byte-identical to full copies
Server version Tue 24 Nov 2026 (Receipts Last-Modified 14:15:56 GMT). build_incremental_copy.py output vs a full copy:
- FiledDocs.txt: identical sha256 (incremental downloaded 4,330,122 of 143,022,661 bytes)
- D2Totals.txt: identical sha256 (1,372,499 of 59,187,159 bytes)
- Receipts.txt: identical sha256 3b6d48cc...a5a42b, 1,065,520,269 bytes (24,298,227 bytes downloaded). The full copy
  for comparison was downloaded by the user in a browser (data/raw/isbe/Receipts_20261124_manual.txt, gitignored):
  scripts/fetch_isbe.py's plain full GET timed out twice (no response in 120 s; full_download*.log), and a full copy
  in 50 MB range pieces (full_copy_by_ranges.py) was stopped part way once the user's copy matched.
- compare_result.json: written before the Receipts retry; its Receipts row compared against the Nov 20 copy and is
  NOT a valid comparison (superseded by the line above).
First real run of the new incremental scripts/fetch_isbe.py (Nov 20 copy -> Nov 24): 173 s for all files, Receipts
24,298,227 bytes downloaded, result sha256 equal to the user's download (first_real_incremental_run.log).
Test copies in data/raw/isbe_incremental_test and isbe_full_by_ranges_test were deleted afterwards (1+ GB each).
