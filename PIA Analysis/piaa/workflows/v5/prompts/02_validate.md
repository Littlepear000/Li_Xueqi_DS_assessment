Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}).

You are the judge. Each candidate approach below was extracted from one reading unit, shown in full. Decide for each whether it is a REASONABLE approach of this project:
1. specificity - is it a specific, identifiable practice (mechanism + use), not a generic phrase?
2. digital - is it related to digital technology, data or AI?
3. category - is the category right? If another category fits better, correct it.
4. evidence - do the cited sentences actually state the practice, and does the adoption value follow from them?

Give exactly one verdict:
- accept   : reasonable as stated
- revise   : reasonable, but the practice wording, category or adoption must be corrected (give the corrected values)
- expand   : the unit alone does not let you decide (e.g. unclear whether this project finances it, what the system does, or which practice is meant); more surrounding text is needed
- reject   : not an approach (too generic, not digital, boilerplate, background about another programme, not supported by the evidence)

Return JSON:
{"results": [
  {"approach_id": "A3", "verdict": "accept", "practice": "...", "category": "...", "adoption": "...", "reason": "one line"},
  {"approach_id": "A4", "verdict": "expand", "reason": "cannot tell whether the platform is financed by this project"}
]}
For accept, repeat the given practice / category / adoption unchanged. For revise, give the corrected ones. For expand and reject, only the reason is needed.

=== CANDIDATE APPROACHES ===
{{approaches}}
