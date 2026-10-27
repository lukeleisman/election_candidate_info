# Rerun entry point. Each target runs one step; `make all` runs everything in order.
# Uses the conda env from environment.yml (override with: make PYTHON=/path/to/python ...).
PYTHON ?= conda run --no-capture-output -n election-candidate-info python

# Newest CBOE filing report on disk (file names carry a timestamp, so sort = newest last).
FILING_REPORT = $(shell ls data/raw/cboe/documents/*/"Candidate Filing Report_"*.pdf 2>/dev/null | sort | tail -1)

.PHONY: all candidates fetch-cboe parse-candidates compare-lists ballot-status fetch-isbe committee-proposals committee-review review-rule apply-review

all: candidates fetch-isbe committee-proposals committee-review review-rule apply-review

## Official candidate list (PLAN.md step 2)
candidates: fetch-cboe parse-candidates compare-lists ballot-status

fetch-cboe:
	$(PYTHON) scripts/fetch_cboe.py

parse-candidates:
	$(PYTHON) scripts/parse_cboe_filing_report.py "$(FILING_REPORT)"

compare-lists:
	$(PYTHON) scripts/compare_candidate_lists.py

ballot-status:
	$(PYTHON) scripts/build_ballot_status.py

## ISBE campaign-finance bulk files + candidate -> committee evidence (PLAN.md step 3)
fetch-isbe:
	$(PYTHON) scripts/fetch_isbe.py

# Writes evidence only; you confirm committees in data/crosswalk/candidate_committee.csv.
committee-proposals:
	$(PYTHON) scripts/propose_committee_matches.py

# Review sheet you mark (accept = yes/no); reruns keep your marks.
committee-review:
	$(PYTHON) scripts/build_committee_review.py

# Mark clear cases by rule (reviewed_by = rule_v1); judgment calls stay blank.
# See docs/process_committee_review.md.
review-rule:
	$(PYTHON) scripts/apply_review_rule.py

# Rebuild the crosswalk from rows marked yes in the review sheet.
apply-review:
	$(PYTHON) scripts/apply_committee_review.py
