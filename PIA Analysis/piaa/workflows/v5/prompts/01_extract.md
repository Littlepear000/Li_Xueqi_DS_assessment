Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}; approved {{approval_date}}).

Below are reading units of the project's appraisal document. Each sentence has an id like [U12.s3]. For every unit, extract the innovative approaches it describes (zero, one or several). For each approach give:
- practice: the specific practice as a noun phrase, max 12 words, naming the mechanism AND its use (e.g. "mobile money transfers to registered farmers", "drone imagery for road condition surveys")
- what_is_done: one sentence, in your own words, of what the project does with it
- category: Operational | Technological | Financial | Collaborative (exactly one)
- adoption: apply | prospect | discuss
- evidence: 1 to {{max_evidence}} sentence ids from THIS unit that state the practice (the first id is the main evidence)
- reason: one line - why it passes the specificity test and which words decide the adoption value

Do not extract an approach that fails the specificity test, is not digital / data / AI related, or is only background about the country. The same practice stated twice in one unit is one approach.

Return JSON:
{"units": [
  {"unit_id": "U12", "approaches": [
     {"practice": "...", "what_is_done": "...", "category": "Technological", "adoption": "apply", "evidence": ["U12.s3", "U12.s4"], "reason": "..."}
  ]},
  {"unit_id": "U13", "approaches": []}
]}

=== UNITS ===
{{units}}
