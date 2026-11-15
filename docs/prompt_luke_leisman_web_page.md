# Prompt for an agent in ~/Luke/web/luke_leisman_web (written 2026-11-14)

Paste everything below the line into a new Claude Code session started in `~/Luke/web/luke_leisman_web`.

---

Add a page to lukeleisman.com that shows the Chicago 2027 candidate dashboard, built the same way as the
existing council page (`pages/chicago-city-council.html`, registered in `site_config.py`).

Read first: `~/.claude/CLAUDE.md`, this repo's `HANDOFF.md` (deploy: push to `main` = staging, `git push origin
main:live` = live; never delete `lukealfalfa/`), and `pages/chicago-city-council.html` + its `site_config.py` entry.

What to build:
1. `pages/chicago-2027-candidates.html`, a copy of the council page's pattern: a comment block saying what it
   is and where the script comes from, an empty `<div id="candidates-app"></div>`, and
   `<script src="https://lukeleisman.github.io/election_candidate_info/dashboard/app.js"></script>`.
   That script (from the repo `lukeleisman/election_candidate_info`, served by GitHub Pages from `main` →
   `/docs`) injects its own CSS scoped to `#candidates-app`, fetches its JSON from `../data/` next to its own
   URL, and draws everything. Updating that repo updates this page with no website rebuild.
2. Register it in `site_config.py` next to the council entry: not in the nav, title
   "Chicago 2027 Candidates · Luke Leisman".
3. Put every choice in a named, commented setting (URL slug, container id, script URL, nav/no-nav, where it is
   linked from). Don't pick between options on your own; list them and ask me.

Open questions to ask me before building (give a recommendation for each):
- URL: decided, `/chicago-2027-candidates/` (user, 2026-11-14: "fine for now").
- Link it from the homepage "Things I'm building" and Build "Tools for seeing Chicago", like the council page,
  or keep it unlinked while people test it?
- `noindex` while it's in testing? (The page says the data is incomplete and has errors.)

Dependency (not yours to build): the script URL above does not exist yet. The candidate repo is private and
needs (a) an embeddable `docs/dashboard/app.js` + `docs/data/*.json` and (b) to be made public with Pages
turned on. Until `curl -sI <script URL>` returns 200, build and check the page on staging only, and tell me.
Don't push to `live` without my OK.

Check: `python3 build.py`, then the page in headless Chrome locally; after the staging deploy, curl the page
(200) and look at it at phone and desktop width. Report raw results. Don't commit without asking.
