Project: {{project_id}} - {{project_name}}
Country: {{country}} | Vertical: {{vertical}} | Lead practice: {{lead_practice}} | Approval: {{approval_date}}
Sector codes: {{sectors}}
Theme codes: {{themes}}

Keyword screening already found these innovation-related terms in the project documents (term: count): {{keyword_hits}}

Task: identify up to {{max_approaches}} distinct Digital & AI approaches that this project adopts. Prefer approaches that are financed as components or activities over passing mentions. Do not list the same approach twice under different names.

For each approach return:
- approach_name: a short noun phrase (max 12 words)
- description: 1-2 sentences in your own words
- evidence_sentence: ONE sentence copied verbatim from the DOCUMENT TEXT below that best shows the approach
- document_guid: the guid of the document the sentence comes from
- why_innovative: one sentence on what is new (technology, delivery model, partnership, financing, or pilot/scale/replication)

If the project adopts no Digital & AI approach, return an empty list and set innovative to "No". If you can only find weak or ambiguous signals, set innovative to "Unclear" and still list the candidate approaches.

Return JSON:
{"innovative": "Yes" | "No" | "Unclear", "approaches": [{"approach_name": ..., "description": ..., "evidence_sentence": ..., "document_guid": ..., "why_innovative": ...}]}

=== DOCUMENT TEXT ===
{{documents}}
