# PIA Analysis (`piaa`) – package changelog

Package version = `piaa.__version__`. Workflow folders have their own tags (`v1.1`, `r2.0` ...; see README "Version tags").

## 0.3.31 (2026-11-06)
- Database export (Projects sheet): de-duplicate projects.csv on project_id (first row wins), matching the web
  app's load_projects. Fixes the Projects sheet showing one extra row (e.g. P506109 listed twice) so the export
  count equals the in-app count. Approaches sheet and all filters are unchanged.

## 0.3.30 (2026-11-06)
- One-click launchers (start_pia.bat / .sh / .command) now self-heal a broken or half-finished install.
  They check that `piaa` and `fastapi` actually import inside .venv, not just that the .venv folder exists,
  so a first run that failed partway (e.g. a dependency error) is completed on the next run instead of
  starting with "No module named 'piaa'". A still-missing .venv is created; an incomplete one is repaired in place.
- Fixed a Windows quoting bug that produced "'...\PIA' is not recognized" when the repo path contains a space
  (e.g. "PIA Analysis"): the package version is now read via a temp file instead of a FOR /F command, in both
  start_pia.bat and setup.bat.

## 0.3.29 (2026-11-07)
- requirements.lock.txt loosened from exact pins to compatible lower bounds so setup works on Python 3.11, 3.12 and
  3.13. Fixes install failure on 3.11 where the previous pin numpy==2.5.4 (requires Python >=3.12) had no match.
  numpy is bounded >=1.26,<3; pandas >=2.0,<4; other deps use their pyproject floors.

## 0.3.28 (2026-11-07)
- HOW TO USE.html: Setup step now flags that the API key must start with sk-ant-api03- (Console account key),
  not sk-ant-usr- (a user/session token, which fails with 401).

## 0.3.27 (2026-11-07)
- One-click launch from a fresh git clone: root start_pia.bat / .command / .sh now BOOTSTRAP on first run
  (find Python, build the private .venv inside "PIA Analysis", install requirements.lock + the package) and then
  start the app - no separate setup step, no dependence on PATH/conda. Fixes the old launcher that assumed piaa was
  already installed (and a Windows quoting bug in its Python-version check).
- Python 3.11 / 3.12 / 3.13 supported: launcher/setup detection updated, requires-python >= 3.11.
- "HOW TO USE.html" added at the repo root (and kept in the package) with a collapsed "No Python yet?" section;
  it is the quick guide (the old README_RUN_WEB_APP.md is superseded).

## 0.3.26 (2026-11-07)
- Added "HOW TO USE.html": a short, minimal 7-step quick guide (install, add data, start, setup, run, review, export).

## 0.3.25 (2026-11-07)
- Documents are completed automatically during a run: before extraction, the pipeline checks the project's local
  documents and, for any missing wanted type (PAD/PID/ISR/ProjectPaper/ProgramDocument), fetches the text from the
  public WBG Documents API into output/supplement_documents/ (no key; offline-safe - a run never fails if the API is
  unreachable). New module piaa/acquire.py; an "acquire" step appears in each run's trace. Disable with PIAA_ACQUIRE=0.
- Supplement documents moved from raw_data/api_supplement to output/supplement_documents (raw_data can now ship empty;
  the recipient drops in their own projects.csv + documents/). Legacy raw_data/api_supplement is still read if present.
- approach_examples.json moved from raw_data to output/ (old raw_data copy still read until re-saved).
- Note: the background/ folder is referenced only in docstrings, not at runtime - safe to delete from a shipped package.

## 0.3.24 (2026-11-07)
- Windows packaging for an isolated install: new setup.bat (finds Python 3.10-3.12 via the py launcher, builds a private
  .venv inside the package folder, installs requirements.lock.txt + the package, creates config\local.env), start.bat
  (uses only .venv - never global/conda; errors clearly if .venv is missing, keeps R-to-restart), uninstall.bat
  (removes .venv, keeps output/ , config\local.env and data).
- Default port 8765 -> 18765 (127.0.0.1 only). Override order: PIAA_PORT env > config\local.env > default; if the port
  is busy the next free port up to +10 is used and the real URL is printed.
- Dependencies: added numpy (imported but previously undeclared); no Jupyter tooling was present to remove. New
  requirements.lock.txt pins the runtime deps only. package_release.py builds a clean zip (excludes .venv, output,
  __pycache__, *.pyc, config\local.env, caches, .git, egg-info).
- Docs: new self-contained README.html (TOC, copy buttons, troubleshooting); README.md trimmed to a short pointer.

## 0.3.23 (2026-11-07)
- Pattern workflow r3.1 (replication confirmed/likely + scaling, database-only), workflow v6.7 context, analytics page,
  API supplement documents. (Committed in a parallel session; see commit history.)

## 0.3.22 (2026-11-07)
- Database export (both tabs): the final workbook leaves out projects approved before 2019-01-01 and projects with
  status Dropped or Canceled; the Approaches tab is restricted to the kept projects. Controlled by MIN_APPROVAL_DATE
  and EXCLUDE_STATUS in piaa/db_export.py. (Current data: 155 -> 144 projects; 11 removed.)

## 0.3.21 (2026-11-07)
- Workflow **v6.8**: pre-2019 novelty check loosened - `novelty.fail_on: [common]`. An approach is now dropped only when
  the model judges the KIND of approach was already CLEARLY WIDESPREAD / standard MDB practice before 2019; "already in
  use before 2019, but not everywhere" (in_use) is kept. (v6.5-v6.7 dropped both in_use and common, which zeroed out
  almost every project.)

## 0.3.20 (2026-11-07)
- Workflow **v6.7**: prompts now frame judgement in the multilateral-development-bank context (WBG/UN/IMF/IDB/AIIB/...),
  add a project life-cycle note (PID -> PAD/Project Paper -> ISR), and the pre-2019 novelty check judges against
  real MDB / international-development practice rather than development projects in general or global industry.

## 0.3.19 (2026-11-06)
- Web app Export (Database page) uses the 0.3.18 format; with "All projects + rejected approaches" the Approaches tab
  keeps an `approach_status` column so rejected rows can be told apart.

## 0.3.18 (2026-11-06)
- Excel download: every cell in Aptos. Approaches tab trimmed - removed innovation_basis, innovation_cues,
  category_code, category_reason, solution, solution_code, theme, approach_status, origin, replication_links;
  new column `evidence_page` (kept even while empty: the local .txt documents have no page breaks yet).

## 0.3.17 (2026-11-06)
- Database -> Export now downloads ONE Excel file to the browser (`PIA_database_<date>.xlsx`, copy kept in
  `<output>/exports/`) with two tabs: **Projects** (every projects.csv column + review status, innovative, number of
  approaches, latest workflow tag / run, innovation tier) and **Approaches** (one row per project x approach, current
  database state incl. manual edits, all approach columns: category + category reason, solution, sector, adoption,
  innovation basis / cues, evidence sentence and document, replication, workflow tag of the run). Formatted: dark
  header, frozen ID columns, filters on every column, fitted column widths, numbers with thousands separators,
  Approaches text wrapped with even row heights. Menu: all projects / pushed only / all + rejected approaches.
  New module `piaa/db_export.py`, endpoint `GET /api/download/database.xlsx`.

## 0.3.16 (2026-11-06)
- Approach Spot runs several projects at the same time: "Projects at the same time" (1-4, default 3) on the start page.
  The run is still one job with one Stop button; the header, timer and session panel show how many projects are running.
- Heat map / session colours: earlier result (from before this session) = dark blue, running = yellow, new this
  session = light green, reviewed = dark green, pushed = navy, failed = red, not run = grey. Filters and tiles follow.
- Basic info: four columns only when the card is wide enough, otherwise label | value; long values and sector chips
  wrap inside the card (no more text running past the card edge). Checked in a headless browser at 1440, 1180 and
  1050 px on every page with an audit for elements sticking out of their card and clipped buttons: none found.

## 0.3.15 (2026-11-06)
- Status colours: running = yellow, generated = light green, reviewed = dark green (heat map, legend, status pills,
  session tiles); the running job pill is yellow.
- Approach Spot: the project header (ID, Prev / 1 of N / Next, workflow, Regenerate) stays at the top while scrolling;
  the run report is compact (per-project times folded; click a row to open that project).
- Advanced subset box: select and number box on one line, same height; "Quick test: random 10" below (no longer cut);
  the info line is a small badge.
- Workflow dropdown on the project page: "v6.6 — innovation test, ..." instead of "v6.6 — v6 - innovation test, ...".
- Layout guards for the whole app (checked in a headless browser at 1440 px and 1100 px on every page): buttons never
  wrap or get cut, number inputs styled like text inputs, button rows and headers wrap instead of overlapping, the main
  column may shrink (the Database table scrolls inside its box, Analytics cards re-flow, two-column blocks stack below
  1180 px), "+ Add" on the Setup examples panel no longer cut.

## 0.3.14 (2026-11-06)
- Workflow **v6.6**: short, fixed-shape justifications (digital core, what is new, adoption) and a `category_reason`.

## 0.3.13 (2026-11-06)
- Workflow **v6.5**: pre-2019 check relaxed - one call, rare or absent before 2019 = innovative; in use / common = dropped.
- Approach Spot: "Generate all remaining (N)" shows how many projects are left, explains that they run one after another
  (not in parallel), and is disabled while a run is in progress.

## 0.3.12 (2026-11-06)
- Approach Spot, Projects = From database: **Advanced: take a subset** - All matching / Random N / First N (by project ID)
  of the projects matching the review-status filter, with a number box (default 10) and a "Test: random 10" button.
  A random subset is drawn anew when the session starts; the summary shows e.g. "random 10 of 154 matching".

## 0.3.11 (2026-11-06)
- Approach Spot / Database drawer: "Innovative?" moved out of Basic info (projects.csv facts) into a separate
  **Assessment result** strip - Innovative? (reviewer override + History), approaches (+ mentioned only), innovation
  tier with keyword hits, review status, latest run (tag, time, duration). In Approach Spot it sits at the top of the
  Innovation assessment card, so it is hidden together with the stale results while a run is in progress.
- Session panel: structured - workflow tag and start time, progress bar (reviewed / total), four tiles
  (waiting, queued, failed, reviewed), job status pill with progress.
- More spacing: cards, grids, Basic info rows, card headings.

## 0.3.10 (2026-11-06)
- Workflow **v6.4**: digital & AI must be the core of an approach (prompts + a digital question in the final check).

## 0.3.9 (2026-11-06)
- Workflow **v6.3**: pre-2019 novelty check (3 rounds; one "existed / common before 2019" answer drops the approach).

## 0.3.8 (2026-11-06)
- Approach Spot: while a project is running, its Innovation assessment and Workflow trace are hidden and replaced by a
  "Running <workflow tag>…" placeholder (spinner); Save edits and Push are disabled. The new results appear when the run ends.

## 0.3.7 (2026-11-06)
- Fix: false "server is older than this page" banner. The page version was hard-coded in app.js (0.3.4) and not bumped.
  The server now injects the version found on disk (`piaa/__init__.py`) into the page; the banner appears only when the
  code on disk is newer than the running server (i.e. a restart is really needed). No manual bump in app.js any more.

## 0.3.6 (2026-11-06)
- Fix: every page load logged `h11 LocalProtocolError: Too much data for declared Content-Length` - the favicon
  route answered 204 (no content) with a JSON body `{}`. It now returns an empty 204. No effect on results.

## 0.3.5 (2026-11-06)
- Approach Spot: the red banner of a failed previous run now has **▶ Regenerate with <workflow tag>** and **Dismiss**
  (hides the banner for that run only); while a run is in progress it says so instead.
- (0.3.4 was taken by a parallel change without a changelog entry.)

## 0.3.3 (2026-11-06)
- Workflow **v6.2**: fix for the aggregate crash (`'Evidence' object has no attribute 'start'`) when a Data Sheet
  sentence is attached as extra evidence. v6.2 also contains the token-saving changes of 0.3.2 in `v6/steps.py`.

## 0.3.2 (2026-11-06)
- Token saving, no prompt or workflow change (applies to every workflow): the first call with a given system prompt is
  sent alone so parallel calls read the prompt cache; optional cheaper model per step (`step_models`, e.g. codes / merge);
  optional reuse of stored answers for identical requests (`<out>/cache/llm`, off for A/B QC runs); prompt-cache writes
  counted in the cost estimate; DeepSeek peak / off-peak notice. Set on the Setup page (card "Token saving") or with
  `--step-model`, `--reuse-answers`, `--no-warm-cache`.
- Web app: the sidebar footer shows the package version and the latest workflow tag, read from the package.

## 0.3.1 (2026-11-06)
- Workflow **v6.1**: sector only (no theme); one approach per sector x category.
- Export: approach theme columns are left out when no approach has a theme.

## 0.3.0 (2026-11-06)
- New workflow **v6.0** (from v5): innovation test, project-level innovation screen, PAD Data Sheet exclusion,
  `reject_code` (see `piaa/workflows/v6/CHANGELOG.md`).
- `Approach` gains `innovation_basis` and `innovation_cues` (stored in the record JSON, exported in project_approaches);
  data dictionary updated (innovation_tier, innovation_basis, innovation_cues, reject_code, evidence_source).

## 0.2.2 (2026-11-06)
- All dropdowns (13 in the web app): the browser's native arrow is replaced by one chevron placed 10 px inside the right edge
  (8 px in compact filters); text no longer runs under the arrow; consistent hover / focus / disabled styles.
- Run timer (Approach Spot): while a run is in progress the page shows a live clock for the current project and the whole run;
  when the run ends, a report at the top lists every project with its result (done / failed / reused / cancelled) and time,
  plus total and average time. The project's Runs tab has a Duration column.
- Launchers next to `PIA Analysis/`: `start_pia.command` (macOS), `start_pia.bat` (Windows), `start_pia.sh`.

## 0.2.1 (2026-11-06)
- Approach Spot: while a run is in progress, Regenerate / Run is disabled and a red **Stop** button is shown.
  Stop: no further project starts; the current project's model calls stop at the next call (a request already sent finishes);
  its partial result is discarded and the previous result is kept. Only one run at a time (server returns 409 otherwise).
- Runs refuse to start when the chosen provider has no API key (message shown at the top of the page; nothing is run).
- Errors are shown at the top of the project page; a stored failed run is labelled as the previous run with its time.
- Fix: the workflow's model name (claude-...) is applied only with the Anthropic provider; DeepSeek / OpenAI-compatible
  runs keep the model chosen on the Setup page. The app's shared settings are no longer modified by a run.
- Setup: "Save & re-index" split into **Save** (settings only) and **Reindex projects and documents**.

## 0.2.0 (2026-11-06)
- Version tags: `releases.json` per workflow folder, `workflow_tag` + `package_version` on every record, the `runs` table,
  field history, exports, mart and pattern manifests; `piaa workflows`, `piaa release <folder> --note ...`.
- Folder hash excludes CHANGELOG.md.
