Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}; approved {{approval_date}}).

Below are reading units of the project's appraisal document. Each unit header lists its digital_cues and innovation_cues; each sentence has an id like [U12.s3]. For every unit, extract the innovative approaches it describes (zero, one or several). For each approach give:
- practice: the specific practice as a noun phrase, max 12 words, naming the mechanism AND its use (e.g. "mobile money transfers to registered farmers", "drone imagery for road condition surveys")
- what_is_done: one sentence, max 20 words, in your own words: what the project does with it
- category: Operational | Technological | Financial | Collaborative (exactly one)
- adoption: apply | prospect | discuss
- innovation_basis: "New <product | service | process | delivery arrangement | organizational practice>: <what is new, max 12 words> - cue: '<1-3 words from the unit>'"
- evidence: 1 to {{max_evidence}} sentence ids from THIS unit that state the practice (the first id is the main evidence)
- category_reason: "<Category>: <why this category and not another, max 12 words>" (e.g. "Financial: changes how transfers are paid, not how they are targeted")
- reason: "Digital core: <system, max 8 words> | Not routine: <why, max 8 words> | Adoption: '<deciding words>'"

Do not extract an approach that fails any of the three tests (specificity, digital, innovation), or that is only background about the country or another programme. Routine requirements (fiduciary, safeguard, legal or disbursement conditions; compliance audits or IT / cyber assessments required as conditions; standard M&E and reporting; standard IT procurement or upgrades) are not approaches. Do not extract from units marked legal_condition. The same practice stated twice in one unit is one approach.

Return JSON:
{"units": [
  {"unit_id": "U12", "approaches": [
     {"practice": "...", "what_is_done": "...", "category": "Technological", "adoption": "apply", "innovation_basis": "New service: satellite-based crop insurance payouts - cue: 'for the first time'", "category_reason": "Technological: the remote-sensing index is the core mechanism", "evidence": ["U12.s3", "U12.s4"], "reason": "Digital core: satellite rainfall index | Not routine: replaces field loss assessment | Adoption: 'will finance'"}
  ]},
  {"unit_id": "U13", "approaches": []}
]}

=== UNITS ===
{{units}}
