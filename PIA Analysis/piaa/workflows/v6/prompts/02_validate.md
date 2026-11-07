Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}).

You are the judge. Each candidate approach below was extracted from one reading unit, shown in full, with the unit's digital_cues and innovation_cues and the extractor's innovation_basis. Decide for each whether it is a REASONABLE innovative approach of this project:
1. specificity - is it a specific, identifiable practice (mechanism + use), not a generic phrase?
2. digital & AI - is digital technology, data or AI the CORE of the practice (a named platform, system, app, algorithm, dataset, digital channel or AI model that does the work)? Beneficiary categories, partnerships, agent networks or bank accounts without a named digital system, and generic programme design (accelerator streams, grants, training) fail - reject_code not_digital.
3. category - is the category right? If another category fits better, correct it.
4. evidence - do the cited sentences actually state the practice, and does the adoption value follow from them?
5. innovation - does it pass the innovation test (a new product, service, process, delivery arrangement or organizational practice for a development challenge in this project's context), or is it a routine requirement (fiduciary, safeguard, legal or disbursement condition; compliance audit or IT / cyber assessment required as a condition; standard M&E and reporting; standard IT procurement or upgrade)? Innovation cues support the test but do not decide it.

Give exactly one verdict:
- accept   : reasonable as stated
- revise   : reasonable, but the practice wording, category, adoption or innovation_basis must be corrected (give the corrected values)
- expand   : the unit alone does not let you decide (e.g. unclear whether this project finances it, what the system does, whether it is new or routine, or which practice is meant); more surrounding text is needed
- reject   : not an approach; give exactly one reject_code:
    generic | not_digital | not_innovative | legal_or_compliance_condition | background_or_other_programme | unsupported_by_evidence

Return JSON:
{"results": [
  {"approach_id": "A3", "verdict": "accept", "practice": "...", "category": "...", "adoption": "...", "innovation_basis": "...", "reason": "one line"},
  {"approach_id": "A4", "verdict": "expand", "reason": "cannot tell whether the platform is financed by this project"},
  {"approach_id": "A5", "verdict": "reject", "reject_code": "legal_or_compliance_condition", "reason": "cyber-risk assessment required as a disbursement condition"}
]}
reason (max 20 words, no filler): accept/revise -> "Digital core: <system> | Innovative: <what is new> | Category: <why>"; reject -> the one decisive fact (e.g. "disbursement condition, not a new practice"); expand -> what is missing.
For accept, repeat the given practice / category / adoption / innovation_basis unchanged. For revise, give the corrected ones. For expand only the reason is needed; for reject the reject_code and the reason.

=== CANDIDATE APPROACHES ===
{{approaches}}
