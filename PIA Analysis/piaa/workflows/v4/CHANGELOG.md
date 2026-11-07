# Workflow v4

- 2026-11-06  New approach definition (replaces the DDAT-based v2/v3 definition for the main analysis).
  - An approach = a digital / data / AI-related innovation in one of the four working-paper categories: Operational, Technological, Financial, Collaborative.
  - Sentence classification returns category + adoption (apply | prospect | discuss) + short label; the taxonomy and rules sit in a cached system prompt.
  - Every coded passage gets ONE sector and ONE theme from the project's own projects.csv lists (second LLM step).
  - Passages with the same (category, sector, theme) collapse into ONE approach; `number_of_evidence` counts them; adoption at approach level = apply if any evidence is apply, else prospect, else discuss.
  - Headline figures count approaches with adoption = apply only.
  - Database: one row per evidence (approach_evidence table) plus the approach table; Excel export expands evidence_1..n into columns.

- **v4.0** 2026-11-06  First tagged state (version tags introduced in piaa 0.2.0).
