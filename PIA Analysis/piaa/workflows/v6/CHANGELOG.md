# Workflow v6 — changelog

## v6.8 (2026-11-07)
- `novelty.fail_on` changed from `[in_use, common]` to `[common]`: the pre-2019 check now drops an approach only when the
  model judges the kind of approach was already clearly widespread / standard practice across MDB / international-
  development operations before 2019. "Already in use before 2019 but not everywhere" (in_use) is now KEPT as innovative.
  Reason: v6.5-v6.7 removed almost every approach in every fiscal year because most digital practices had been piloted
  somewhere by an MDB before 2019; the stricter bar left near-zero approaches portfolio-wide.

## v6.7 (2026-11-07)
- `00_system`: new CONTEXT block (this is a multilateral development bank operation; judge "innovative" against normal
  practice across MDB / international-development operations - WBG, UN, IMF, IDB, AIIB, ADB, ... - not one project, one
  country or global industry) and a PROJECT LIFE CYCLE note (PID = identification/plans, PAD / Project Paper / Program
  Document = appraisal/committed design = primary source, ISR = implementation; same practice across stages = one approach).
- `06_novelty` Q2 and `novelty.statement`: the pre-2019 check now asks whether the KIND of approach was already applied
  in MDB / international-development operations before 2019 (rare_or_absent kept; in_use / common dropped), not whether
  the technology existed anywhere in the world.

## v6.6 (2026-11-06)
- Sharper justifications. `00_system` adds STYLE OF REASONS: max 20 words, telegraphic, name the concrete digital /
  data / AI system and what it changes, no filler ("leverages technology", "enhances efficiency" ...), fixed shapes.
- `01_extract`: `innovation_basis` = "New <type>: <what is new> - cue: '<words>'"; new field `category_reason` =
  "<Category>: <why this category and not another>" (shown as the category rationale);
  `reason` = "Digital core: <system> | Not routine: <why> | Adoption: '<words>'"; `what_is_done` max 20 words.
- `02_validate` / `03_revalidate`: judge reason "Digital core | Innovative | Category" (max 20 words) or, for reject, the
  one decisive fact; a revised category takes its reason from the "Category:" slot. `05_merge` description max 25 words,
  `06_novelty` reason "Digital: ... | Before 2019: ...".

## v6.5 (2026-11-06)
- The pre-2019 check was too strict (v6.3/v6.4 dropped everything: any one of three answers "already existed" failed).
  Now ONE call per project, temperature 0. Question 2 asks for an overall judgement of how established the kind of
  approach was before 2019: `rare_or_absent` (basically did not exist, or only a few early pilots) -> kept as innovative;
  `in_use` (on balance already in use) or `common` (clearly widespread) -> dropped (`existed_before_2019`).
  Question 1 (digital & AI core) unchanged. Config: `novelty.rounds: 1`, `fail_on: [in_use, common]`.

## v6.4 (2026-11-06)
- Digital & AI made explicit. `00_system`: the DIGITAL & AI TEST now requires digital technology, data or AI to be the
  CORE of the practice (a named platform, system, app, algorithm, dataset, digital channel or AI model), with failing
  examples: beneficiary typologies, partnerships / agent networks / bank accounts without a named digital system,
  accelerator or grant programme design. `01_extract` reason and `02_validate` / `03_revalidate` question 2 follow it.
- `novelty` step (`06_novelty`) asks a second question in every round: digital & AI core / incidental / none.
  Anything but `core` (`novelty.digital_pass`) drops the approach with reject_code `not_digital`.

## v6.3 (2026-11-06)
- New step `novelty` (prompt `06_novelty`) after `merge`: each final approach (with its source paragraph) is judged
  against "This kind of innovative approach was not common before 2019", in up to 3 independent rounds (own client at
  temperature 0.7, round number in the prompt so stored answers are not reused across rounds). One answer
  `common_before` or `existed_before` drops the approach as not innovative (`reject_code = existed_before_2019`);
  later rounds only ask about the approaches still in. Kept approaches show "novelty check: 3/3" in `why_innovative`.
  Config block `novelty` (year, rounds, statement, fail_on, temperature).

## v6.2 (2026-11-06)
- Fix: `aggregate` crashed with `AttributeError: 'Evidence' object has no attribute 'start'` when a Data Sheet sentence
  was attached as extra evidence (Evidence uses `char_start`). Every project with an attached Data Sheet sentence failed in v6.0 / v6.1.

## v6.1 (2026-11-06)
- `codes` (`04_codes`): one SECTOR per approach from the project's projects.csv list; no theme is assigned.
- Theme is not part of the result: `Approach.theme` is empty, evidence rows have no theme column, and the export leaves
  the approach theme columns out when no approach has one.
- `merge` (`05_merge`): grouping is deterministic by `merge.group_by: [sector, category]` - all accepted practices with the
  same sector and the same working-paper category become ONE approach (evidence pooled, member practices listed in the
  description, adoption = highest). One model call only names the multi-member groups.
- `00_system`: extract the project's own distinctive innovations, not every digital activity it mentions.
- Target: about 3 approaches per project on average (upper bound = sectors used x 4 categories).

## v6.0 (2026-11-06)
Created from v5.0. Problem: v5 extracted any specific digital practice, innovative or not, because (1) the innovation
keyword dictionary was no longer used beyond its `enabling_technologies` dimension, and (2) the prompts had no novelty test
and did not exclude the PAD Data Sheet (example: P176935-A1, a disbursement condition requiring an independent cyber-risk
assessment of the MIS, accepted as an "Operational" approach).

Python (`steps.py`, `config.yaml`)
- New step 0 `screen` (as in v1): distinct hits across all 7 dictionary dimensions -> `innovation_tier` High (>=4) /
  Moderate (2-3) / Low (0-1) on every record. `screening.gate: false` by default (informational); when true only
  High / Moderate projects are extracted.
- `candidates`: per unit, `innovation_cues` = hits of the non-technology dimensions (innovation, innovation_cycle,
  results_based_management, innovation_types, enabling_processes, public_good). The digital cue stays the candidate
  filter. Unit headers given to extract and validate show `digital_cues=` and `innovation_cues=`.
- `candidates`: PAD Data Sheet units are marked `legal_condition` (patterns in `legal_conditions.legal_patterns`; the Data
  Sheet zone from the first header in the first 25% of units to the first numbered paragraph / STRATEGIC CONTEXT) and
  not sent to extraction.
- `merge`: Data Sheet sentences that share the practice's content words (>= 2 words and >= 40%) are attached as extra
  evidence of that approach (`evidence_source = legal_condition`).

Prompts
- `00_system`: three tests - specificity, digital, INNOVATION (new product / service / process / delivery arrangement /
  organizational practice; routine fiduciary, safeguard, legal, disbursement, compliance / IT-cyber audit, M&E and
  IT-procurement requirements fail). Innovation cues support but do not decide. General exclusions add the Data Sheet
  tables, effectiveness / disbursement conditions and dated covenants.
- `01_extract`: new field `innovation_basis`; `reason` addresses all three tests; no extraction from legal_condition units.
- `02_validate`, `03_revalidate`: question 5 (innovation); rejections carry `reject_code` = generic | not_digital |
  not_innovative | legal_or_compliance_condition | background_or_other_programme | unsupported_by_evidence.

Output
- Project: `innovation_tier` (already a column). Approach: `innovation_basis`, `innovation_cues` (also in
  `why_innovative`). Evidence rows: `innovation_cues`, `innovation_basis`, `evidence_source`. Exclusion log: `reject_code`.

Acceptance check (for the user's run): P176935 - A1 (cyber-risk assessment as a disbursement condition) is rejected with
legal_or_compliance_condition or not_innovative, or no longer extracted because its unit is in the Data Sheet; the ML
poverty-mapping approach is still accepted; n_approaches drops well below 61.
- **v6.9** 2026-11-07  Scope step (first step): approval date >= `scope.min_approval_date` (2019-01-01, calendar
  date) and status not in `scope.exclude_status` (Canceled, Dropped); a project with no approval date is out of
  scope unless `keep_missing_date`. Out-of-scope projects are not read, get no model calls and no document
  acquisition; the web app shows review status "out of scope" and drops their earlier run results (manual rows
  kept). Pattern workflow r3 skips them. Helper: `piaa/scope.py`.
