# Workflow v5 — changelog

## v5.0 (2026-11-06)
- New unit of analysis: an approach is a *specific, identifiable practice* (mechanism + use) related to digital / data / AI,
  mapped to one of the four working-paper categories. Generic phrases fail the specificity test and are not extracted.
- One document per project: the newest PAD (fallback Project Paper, Program Document, PID).
- Reading units: numbered PAD paragraphs (else ~1,200-character sentence windows) replace per-sentence candidates (v4).
- Extraction returns sentence ids, not text: evidence is verbatim and anchored by construction.
- Judge step with four questions and verdicts accept / revise / expand / reject; `expand` widens the unit by half a page
  on each side (`validate.expand_chars`) and judges again. Rejections are logged with reasons.
- Sector and theme per accepted practice (from projects.csv); duplicate practices merged in one call; `number_of_evidence`
  = pooled evidence sentences.
- Works with any provider of the LLM client (Anthropic, DeepSeek, OpenAI-compatible, mock); token usage and a list-price
  cost estimate are recorded on every record.

- **v5.0** 2026-11-06  First tagged state (version tags introduced in piaa 0.2.0).
