Project: {{project_id}} - {{project_name}} ({{country}}, {{vertical}}, {{lead_practice}})

Approach to classify:
- name: {{approach_name}}
- description: {{description}}
- evidence (verbatim, from {{doc_type}} dated {{doc_date}}): "{{evidence}}"
- why innovative: {{why_innovative}}

Context around the evidence (verbatim):
"{{context}}"

=== CATEGORY TAXONOMY (WBG Digital & AI Implementation Plan FY26-30) ===
{{taxonomy}}

=== SECTORS === (the project's own sector codes with their share; choose exactly one)
{{sector_options}}

=== THEMES === (the project's own theme codes with their share; choose exactly one)
{{theme_options}}

Task: assign
1. category_solution: the ONE solution (S1-S10, or SX for an approach that is primarily about digital trust, safety and security) that the approach fits best. Use "none" if the approach is not a Digital & AI approach at all, i.e. no solution applies. The pillar is derived automatically from the solution, so do not choose a pillar;
2. sector: the ONE sector from the SECTORS list that the approach most directly serves (copy the name exactly, without the percentage);
3. theme: the ONE theme from the THEMES list that the approach most directly advances (copy the full name exactly, without the percentage).

Give a confidence between 0 and 1 and a one-sentence rationale for each.

Return JSON:
{"category_solution": {"code": "S6", "confidence": 0.7, "rationale": "..."},
 "sector": {"value": "...", "confidence": 0.7, "rationale": "..."},
 "theme": {"value": "...", "confidence": 0.6, "rationale": "..."}}
