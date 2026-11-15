"""Google passes: which candidates each pass covers, where its rows and raw files go.
Shared by next.py and append.py (added 2026-11-14 for the social-media rerun).

Pick a pass with --pass NAME (default "first"). Each pass has its own output CSV, so a candidate
done in one pass is still pending in another.
"""
import os

# Repo root = two folders up from this file.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENDORSEMENTS_DIR = f"{REPO}/data/endorsements"

# The first-round output; also the "earlier row" shown by next.py for the rerun.
FIRST_PASS_CSV = f"{ENDORSEMENTS_DIR}/candidate_campaign_sites_google.csv"

# Extra column for the social rerun only (user, 2026-11-14: keep potential endorsements).
# Endorsements that Google's result snippets mention ("endorsed by ...") but that were NOT read on a
# loaded page. Leads only: Google's text can be stale or wrong (memory: don't trust Google text).
ENDORSEMENT_LEADS_COLUMN = "endorsement_leads_from_results"

PASSES = {
    # First round, 2026-11-12..14, 161/161 done. Rows 1-102 (through ALD-27-004) used a QUOTED office
    # phrase, which dropped social profiles whose bio lacks the phrase; the rest were unquoted.
    "first": {
        "output_csv": FIRST_PASS_CSV,
        "earlier_csv": f"{ENDORSEMENTS_DIR}/candidate_campaign_sites.csv",  # first websearch pass
        "raw_suffix": "",            # data/raw/google_search/<id>.txt, second search <id>_2.txt
        "last_candidate_id": None,   # None = every candidate in scope
        "extra_columns": [],
    },
    # Social-media rerun (user OK 2026-11-13; started 2026-11-14): the first 102 again, UNQUOTED, with the
    # Links section, so social profiles show up. Same query builder as the first pass's unquoted rows.
    "social_rerun": {
        "output_csv": f"{ENDORSEMENTS_DIR}/candidate_campaign_sites_google_social_rerun.csv",
        "earlier_csv": FIRST_PASS_CSV,  # compare with the first Google round, not the websearch pass
        "raw_suffix": "_s",            # <id>_s.txt, second search <id>_s2.txt
        "last_candidate_id": "ALD-27-004",  # 102nd candidate in candidates_cboe.csv order
        "extra_columns": [ENDORSEMENT_LEADS_COLUMN],
    },
}
DEFAULT_PASS = "first"


def pass_from_argv(argv):
    """(pass name, argv without --pass NAME)."""
    if "--pass" in argv:
        position = argv.index("--pass")
        name = argv[position + 1]
        assert name in PASSES, f"unknown pass {name}; choose from {sorted(PASSES)}"
        return name, argv[:position] + argv[position + 2:]
    return DEFAULT_PASS, argv
