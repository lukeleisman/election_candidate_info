# Endorsement source re-fetch, 2026-11-24

`make fetch-endorsements` (87 approved sources, one request at a time): 51 unchanged, 33 changed, 3 errors.
Per-source results: data/raw/endorsements/last_run.csv (gitignored; snapshots under data/raw/endorsements/<source_id>/).
Logs here: fetch.log, endorsements.log, dashboard.log.

How "changed" pages were read: unified diff of the newest .txt snapshot vs the previous one (2026-11-14),
added lines only. 30 of 33 were headline/menu/event-calendar churn. New endorsement text on 3 candidate pages,
entered as 5 unreviewed rows in data/endorsements/endorsements_manual.csv:
- gilsenan-007  ALD-32-002 <- Better Streets Chicago Action Fund
- lawson-012    ALD-44-003 <- Chicago Growth Project (cycle unclear, as the page's other rows)
- leni-039..041 ALD-48-001 <- Jan Schakowsky; Asian American Midwest Progressives; Better Streets Chicago

Non-endorsement notes from changed pages:
- girl_we_know: announces a Feb 2027 guide ("Our next guide will break down the races"); no picks yet.
- blockclub_home: Johnson ballot challenge review continues into December (news, not an endorsement).
Errors: campaign_ald27_olas 403 (try Chrome), mijente_pac_chicago 403 (ActBlue, known), ward40_dems_2026 404
(page gone; find new URL). sierra_chicago_home returned an Incapsula block page (known: Chrome only).
