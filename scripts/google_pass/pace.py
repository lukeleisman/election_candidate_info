"""Wait until the next Google search is allowed, then log it. Run right BEFORE every Google search.

Added 2026-11-13 after a Google "unusual traffic" CAPTCHA on 2026-11-12 (~70 searches in ~90 min at
5 s spacing). Pacing used to be a sentence in INSTRUCTIONS.md that each agent followed on its own;
now the spacing, the hourly cap and the pause after a CAPTCHA are enforced here, across agents,
from one log file.

Usage (from the repo root):
  python3 scripts/google_pass/pace.py            wait if needed, then log one search; prints the wait
  python3 scripts/google_pass/pace.py --captcha  log a CAPTCHA; searches are refused for a while
  python3 scripts/google_pass/pace.py --status   show the log summary, no waiting

Exit codes: 0 = go ahead and search now; 2 = refused (CAPTCHA pause; stop the chunk and report);
3 = waited the longest single wait and is not done yet (run it again).

Log: data/raw/google_search/_pacing_log.csv (gitignored with the rest of data/raw).
"""

import csv
import datetime
import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# Pacing settings (chosen 2026-11-13; the user can change them). First values were 75-120 s and 25 an hour,
# about half the rate that drew the CAPTCHA. 2026-11-13 (user): 63-81 s apart, 35 an hour (was 75-120 s, 25).
# 2026-11-13 late (user): 39 an hour (was 35), so the last 39 candidates of the first pass fit in one hour.
# ---------------------------------------------------------------------------
# Minimum gap between two Google searches, plus a random extra of 0..JITTER seconds, so the gaps are
# uneven rather than a fixed beat (63-81 s with these values).
SECONDS_BETWEEN_GOOGLE_SEARCHES = 63
JITTER_SECONDS = 18
# No more than this many searches in any rolling 60 minutes.
MAX_SEARCHES_PER_HOUR = 39
# After a CAPTCHA, refuse all searches for this long (INSTRUCTIONS.md said "a few hours").
HOURS_PAUSE_AFTER_CAPTCHA = 6
# One call never sleeps longer than this (agent shell commands time out at 10 min); exit 3 = call again.
LONGEST_SINGLE_WAIT_SECONDS = 540

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_PATH = f"{REPO}/data/raw/google_search/_pacing_log.csv"
LOG_COLUMNS = ["time", "event"]  # event: search | captcha


def read_log():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, newline="") as handle:
        return [(datetime.datetime.fromisoformat(row["time"]), row["event"]) for row in csv.DictReader(handle)]


def append_log(event):
    new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(LOG_COLUMNS)
        writer.writerow([datetime.datetime.now().astimezone().isoformat(timespec="seconds"), event])


def earliest_allowed(log, now):
    """(time the next search may start, reason) from the log."""
    searches = [moment for moment, event in log if event == "search"]
    captchas = [moment for moment, event in log if event == "captcha"]
    candidates = [(now, "no wait")]
    if captchas:
        candidates.append((max(captchas) + datetime.timedelta(hours=HOURS_PAUSE_AFTER_CAPTCHA), "captcha pause"))
    if searches:
        gap = SECONDS_BETWEEN_GOOGLE_SEARCHES + random.uniform(0, JITTER_SECONDS)
        candidates.append((max(searches) + datetime.timedelta(seconds=gap), f"spacing ({gap:.0f} s)"))
        last_hour = sorted(moment for moment in searches if moment > now - datetime.timedelta(hours=1))
        if len(last_hour) >= MAX_SEARCHES_PER_HOUR:
            # The oldest search in the window must age out first.
            oldest_to_drop = last_hour[len(last_hour) - MAX_SEARCHES_PER_HOUR]
            candidates.append((oldest_to_drop + datetime.timedelta(hours=1), "hourly cap"))
    return max(candidates, key=lambda pair: pair[0])


def main():
    now = datetime.datetime.now().astimezone()
    log = read_log()
    if "--captcha" in sys.argv:
        append_log("captcha")
        print(f"CAPTCHA logged; searches refused for {HOURS_PAUSE_AFTER_CAPTCHA} h")
        return 0
    if "--status" in sys.argv:
        searches = [moment for moment, event in log if event == "search"]
        print(f"searches logged: {len(searches)}; last hour: "
              f"{sum(moment > now - datetime.timedelta(hours=1) for moment in searches)}; "
              f"captchas: {sum(event == 'captcha' for _, event in log)}")
        allowed, reason = earliest_allowed(log, now)
        print(f"next search allowed at {allowed:%H:%M:%S} ({reason})")
        return 0
    allowed, reason = earliest_allowed(log, now)
    if reason == "captcha pause" and allowed > now:
        print(f"REFUSED: CAPTCHA pause until {allowed:%Y-%m-%d %H:%M}. Stop the chunk and report.")
        return 2
    wait_seconds = (allowed - now).total_seconds()
    if wait_seconds > LONGEST_SINGLE_WAIT_SECONDS:
        time.sleep(LONGEST_SINGLE_WAIT_SECONDS)
        print(f"waited {LONGEST_SINGLE_WAIT_SECONDS} s for {reason}; not done yet, run pace.py again")
        return 3
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    append_log("search")
    print(f"waited {max(wait_seconds, 0):.0f} s ({reason}); search now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
