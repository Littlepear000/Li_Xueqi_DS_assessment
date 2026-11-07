Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}).

Second reading. For each approach below the judge could not decide from the reading unit alone, so about half a page of the document has been added on each side of the unit (the original unit is marked between >>> and <<<). Judge again with the same five questions (specificity, digital & AI as the core of the practice, category, evidence / adoption, innovation - new practice or routine requirement?). This time give a final verdict: accept, revise (with corrected practice / category / adoption / innovation_basis) or reject (with reason and exactly one reject_code: generic | not_digital | not_innovative | legal_or_compliance_condition | background_or_other_programme | unsupported_by_evidence). Do not answer expand.

reason (max 20 words, no filler): accept/revise -> "Digital core: <system> | Innovative: <what is new> | Category: <why>"; reject -> the one decisive fact.

Return JSON:
{"results": [
  {"approach_id": "A4", "verdict": "accept", "practice": "...", "category": "...", "adoption": "...", "innovation_basis": "...", "reason": "one line"},
  {"approach_id": "A6", "verdict": "reject", "reject_code": "not_innovative", "reason": "standard M&E reporting system"}
]}

=== APPROACHES WITH WIDER CONTEXT ===
{{approaches}}
