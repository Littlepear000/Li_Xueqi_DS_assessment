# Workflow v3

- 2026-11-06  v2 + adoption check (applied vs mentioned).
  - Review of v2 output showed that part of the coded sentences describe an approach the project does NOT itself adopt:
    future phases, government vision or expectations, other programmes, lessons from elsewhere, options considered, or systems
    built under a parent project. Sentence-level L1 catches some of this, but not when the sentence itself reads like a plan.
  - New step `adoption` after aggregation: for every project x approach the model re-reads ~1 page of context around the
    strongest sentence and returns `applied` or `mentioned` with a reason category
    (future_plan, aspiration_or_vision, other_program, lesson_or_reference, option_considered, parent_or_prior, unclear),
    a confidence and a re-stated evidence level.
  - Approach status: `validated` (applied, L2/L3) | `mentioned_only` | `referenced_only` (L1 only, not checked as applied).
    Headline counts use `validated` only; mentioned approaches stay in the database with their reason, so the share of
    "mention without adoption" can be reported.
  - Database and exports gain `adoption`, `mention_for`, `adoption_reason` per approach and `n_mentioned_only` per project.
  - `steps_meta` added to the config so the web app can draw the flowchart and trace each step to its code and prompts.
  - Replication links can be verified in the web app (side-by-side evidence of both projects); verdict stored as `replication_verdict`.

- **v3.0** 2026-11-06  First tagged state (version tags introduced in piaa 0.2.0).
