Project: {{project_id}} - {{project_name}} ({{country}}, {{vertical}}, {{lead_practice}})

Below is the full set of approaches extracted for this project, each with its assigned attributes. Re-read the document text that follows and check, for every approach, whether each attribute is a reasonable reading of the document.

{{approaches_block}}

Taxonomy reminder:
{{taxonomy}}

For each approach return a verdict per attribute (category_solution, sector, theme; the pillar is derived from the solution and is not assessed separately):
- "confirmed" if the value is supported by the document;
- "revised" with a replacement value if a different option from the same list fits clearly better (for sector and theme only use options from the project's lists above; for category_solution use S1-S10, SX, or "none" when no Digital & AI solution applies);
- "rejected" if the approach itself is not actually adopted by the project (e.g. it describes another project, a counterfactual, or a generic statement).
Also say whether the project as a whole should be considered to adopt an innovative Digital & AI approach ("Yes", "No" or "Unclear") and give one sentence of reasoning.

Only report approaches where at least one verdict is not "confirmed"; omit fully confirmed approaches.

Return JSON:
{"innovative": "Yes" | "No" | "Unclear", "reasoning": "...",
 "approaches": [{"approach_id": "...",
                 "category_solution": {"verdict": "confirmed"|"revised", "value": "S6", "note": "..."},
                 "sector": {"verdict": ..., "value": "...", "note": "..."},
                 "theme": {"verdict": ..., "value": "...", "note": "..."},
                 "approach": {"verdict": "confirmed"|"rejected", "note": "..."}}]}

=== DOCUMENT TEXT ===
{{documents}}
