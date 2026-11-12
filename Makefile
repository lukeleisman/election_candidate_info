# Rerun entry point. Each target runs one step; `make all` runs everything in order.
# Uses the conda env from environment.yml (override with: make PYTHON=/path/to/python ...).
PYTHON ?= conda run --no-capture-output -n election-candidate-info python

# Newest CBOE filing report on disk (file names carry a timestamp, so sort = newest last).
FILING_REPORT = $(shell ls data/raw/cboe/documents/*/"Candidate Filing Report_"*.pdf 2>/dev/null | sort | tail -1)

.PHONY: all candidates fetch-cboe parse-candidates compare-lists ballot-status fetch-isbe committee-proposals isbe-review isbe-rule candidate-committee finance donor-mix display-tables fetch-ward-offices incumbents candidate-links dashboard

all: candidates fetch-isbe committee-proposals isbe-review isbe-rule candidate-committee finance donor-mix display-tables incumbents candidate-links dashboard

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

# Evidence only: ISBE records + linked committees + name matches (Police District Council left out).
committee-proposals:
	$(PYTHON) scripts/propose_committee_matches.py

# The one confirmation (PLAN.md §3a): CBOE candidate -> ISBE record. Reruns keep your marks.
isbe-review:
	$(PYTHON) scripts/build_isbe_record_review.py

# Mark clear cases by rule (reviewed_by = rule_v4); judgment calls stay blank.
# See docs/process_committee_review.md.
isbe-rule:
	$(PYTHON) scripts/apply_isbe_record_rule.py

# Committees of accepted records (as on Illinois Sunshine) + name matches + manual rows.
candidate-committee:
	$(PYTHON) scripts/build_candidate_committee.py

# Money per candidate (PLAN.md §3 finance decisions; settings in FINANCE_CHOICES).
finance:
	$(PYTHON) scripts/build_finance_tables.py

# Donor types, unique donors, concentration (PLAN.md §3). Needs `make finance` first.
donor-mix:
	$(PYTHON) scripts/build_donor_mix.py

# Ward-by-ward display tables (reshape only) + local dashboard (open dashboard/index.html).
display-tables:
	$(PYTHON) scripts/build_display_tables.py

# City data portal "Ward Offices" (one request), used only to cross-check the incumbents table.
fetch-ward-offices:
	mkdir -p data/raw/city
	curl -sSf --max-time 60 -o data/raw/city/ward_offices_htai-wnw4.json "https://data.cityofchicago.org/resource/htai-wnw4.json?\$$limit=100"

# Hand table of current officeholders -> (i) marker. Feb 2027 election only (see the script).
incumbents: display-tables
	$(PYTHON) scripts/check_incumbents.py

# Every website / social / fundraising link from the three website sources.
candidate-links:
	$(PYTHON) scripts/build_candidate_links.py

dashboard: display-tables incumbents candidate-links
	$(PYTHON) scripts/build_dashboard.py
