Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}; approved {{approval_date}}).

For each candidate sentence below decide whether it describes a digital / data / AI-related innovative approach of this project in one of the four categories. For every match give:
- category: Operational | Technological | Financial | Collaborative
- adoption: apply | prospect | discuss (see rules)
- label: a short noun phrase naming the approach (max 10 words, e.g. "mobile money payments to farmers", "satellite-based crop monitoring")
- reason: one line citing the definition or example relied on, and the words that decide the adoption value

If the sentence describes no such approach, return an empty match list with a short excluded_reason.

Return JSON:
{"results": [
  {"candidate_id": "C1", "matches": [{"category": "Technological", "adoption": "apply", "label": "satellite-based crop monitoring", "reason": "..."}], "excluded_reason": ""},
  {"candidate_id": "C2", "matches": [], "excluded_reason": "grievance redress boilerplate"}
]}

=== CANDIDATES ===
{{candidates}}
