# Pattern workflow r3

- 2026-11-06 - two-column design agreed with the project lead (replaces r2's pairwise page-reading verification):
  - reads the database only (evidence passages + explicit references stored by the Approach Spot workflow);
  - replication at two levels - CONFIRMED (passages state the project replicated / learned from an earlier
    project; source named or identifiable, P-code recorded) and LIKELY (earlier experience without a name +
    verified same approach in an earlier project of another country);
  - scaling = verified same approach in an earlier project of the same country and the same sector;
  - one model call per approach (judges replication level, source and candidate sameness together);
  - the two columns are written back into the database and shown in a new table on the Patterns page.
- **r3.1** 2026-11-07  Loosened scaling (same or closely similar approach, confidence >= 0.5, in an earlier project of the
  same country and sector); candidates also take the similar_approach links stored by the approach workflow; rule-only
  fallback when the model does not run (confirmed = explicit reference to an earlier project next to replication
  language - the logic behind the database's "replicated" column - or a project named in the passages with cue language;
  likely = cue language + similar earlier approach abroad; scaling = similarity >= rule threshold). Web app passes the
  model to the pattern run for any real provider (was Anthropic only, so DeepSeek runs showed "no API key").
- **r3.2** 2026-11-07  Wider funnel after a first live run found only 2-3 replication / 4 scaling: match threshold
  lowered (embedding 0.40 / TF-IDF 0.08), top 8 candidates plus the 3 best earlier approaches of the same country and
  sector; sameness graded in three bands (same >= 0.8, closely similar 0.5-0.7, different) and scaling / likely
  replication accept "closely similar" (0.45 / 0.5); explicit-reference upgrade (model says none, but the full
  documents refer to an earlier project next to replication language and that project has a similar approach ->
  confirmed). Prompts rewritten accordingly.
