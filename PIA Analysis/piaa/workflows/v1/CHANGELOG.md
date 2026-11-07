# Workflow v1

- **v1.0** 2026-11-06  Initial version.
  - Step 0 `screen`: innovation keyword dictionary (working paper, Appendix B), distinct-hit tiers High / Moderate / Low.
  - Step 1 `select_documents`: PAD (else Project Paper, else PID) as primary; latest ISR as supporting.
  - Step 2 `extract`: LLM lists approaches with one verbatim evidence sentence each; Python anchors the sentence to (guid, char offsets) and drops anything it cannot find.
  - Step 3 `match`: LLM assigns pillar (category), solution, one sector and one theme from the project's own code lists.
  - Step 4 `validate`: LLM re-reads the document with the full attribute set as context and confirms / revises each attribute.
  - Step 5 `replication`: explicit cross-references (P-codes, project names) + TF-IDF similarity against all approaches already in the portfolio store.

- **v1.1** 2026-11-06  Pillar derived from solution.
  - Step 3 `match`: the LLM now assigns only the solution (S1-S10, SX, or "none"); the pillar (category) is derived in code
    from `dai_pillars.SOLUTION_BY_ID` (P1: S1-S2, P2: S3-S5, P3: S6-S8, P4: S9-S10, PX: SX), as the Implementation Plan
    maps every solution to exactly one pillar.
  - Step 4 `validate`: verdicts cover category_solution, sector and theme only; a revised solution re-derives the pillar.
  - Web app: the pillar field is read-only; manual edits/additions set the solution and derive the pillar.

Version tags live in `releases.json` (see `piaa.versioning`); `piaa release v1 --note "..."` adds the next one.

- 2026-11-06  Analytics tab rebuilt (web app, workflow-independent).
  - New `GET /api/analytics/v2` (`webapp/analytics.py`): KPI tiles; approaches by sector and by sector x FY;
    AI share within each sector (count- and commitment-weighted); categories x FY and AI share by FY;
    themes and theme mix x FY; sector x category. Uses the current DB state; sector/theme fall back to the
    project's largest coded sector/theme when the approach has none; AI = solution S9 or keyword rule.
  - Front end restyled after the WBG Scorecard (navy band, light page, white cards, icon rings, large light numbers).
  - Interactive explorer: the API also returns slim per-approach records; the page aggregates them by any dimension
    (sector / theme / category / region / vertical / lead practice): count, over time (count or share), AI share, and a
    cross-tab against a second dimension.
