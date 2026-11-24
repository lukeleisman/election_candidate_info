"""One-off look at CBOE's "Candidate List" PDF (ballot order + status), 2026-11-20.

NOT part of the pipeline: nothing reads its output. It records what the 11/9/2026 list
said, so the decisions about IDs / "Challenged" on the page can be checked later.

Input:  data/raw/cboe/documents/2026-11/Candidate List_20261109-1.pdf (from make fetch-cboe)
Output: list_20261109_status.csv (office, ballot_name, status, ballot_position) next to this file.

Rerun from the repo root:
  /opt/anaconda3/envs/election-candidate-info/bin/python analysis/2026-11-20_cboe_candidate_list/extract_candidate_list_status.py
"""

import csv
import re
from pathlib import Path

import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_LIST_PDF = REPO_ROOT / "data/raw/cboe/documents/2026-11/Candidate List_20261109-1.pdf"
OUTPUT_PATH = Path(__file__).resolve().parent / "list_20261109_status.csv"

# A line starting with one of these (and not "Vote for ...") begins a new race.
OFFICE_HEADER_PREFIXES = ("Mayor", "Clerk", "Treasurer", "Alderperson", "Council Member")

# Status words seen at the end of candidate lines on the 11/9 list. "Write-in N/A" rows are skipped.
# OPEN QUESTION: later lists may add other words (e.g. Withdrawn / Removed); lines ending in an
# unknown word are printed below so they are not silently dropped.
KNOWN_STATUS_WORDS = ("Candidate", "Challenged")
CANDIDATE_LINE = re.compile(r"^(.*\S)\s+(" + "|".join(KNOWN_STATUS_WORDS) + r")\s*$")

with pdfplumber.open(CANDIDATE_LIST_PDF) as pdf:
    lines = "\n".join((page.extract_text() or "") for page in pdf.pages).splitlines()

rows = []
current_office = None
position_in_office = 0
for line in lines:
    text = line.strip()
    if text.startswith(OFFICE_HEADER_PREFIXES) and "Vote" not in text:
        current_office, position_in_office = text, 0
        continue
    match = CANDIDATE_LINE.match(text)
    if match and current_office:
        position_in_office += 1
        rows.append([current_office, match.group(1), match.group(2), position_in_office])
    elif current_office and text and not text.startswith(("Vote for", "Write-in")) \
            and not re.search(r"\d{5}$", text) and "Page " not in text:
        print("unrecognized line (check by hand):", text)

with open(OUTPUT_PATH, "w", newline="") as output_file:
    writer = csv.writer(output_file)
    writer.writerow(["office", "ballot_name", "status", "ballot_position"])
    writer.writerows(rows)
print(f"{len(rows)} candidate rows -> {OUTPUT_PATH}")
