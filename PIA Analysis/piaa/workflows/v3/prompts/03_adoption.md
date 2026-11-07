Project {{project_id}} - {{project_name}} ({{country}}; lead practice: {{lead_practice}}; approved {{approval_date}}; status {{status}}).
Approach under review: {{approach_code}} {{approach_name}}.

The sentence-level coding found {{n_rows}} sentence(s) for this approach (levels: {{levels}}). The strongest one is marked >>> below. Read the surrounding text (about one page of the {{doc_type}} dated {{doc_date}}) and decide whether THIS PROJECT actually adopts the approach, or only mentions it.

Decision rules:
- "applied": the project finances, procures, builds, deploys, pilots, scales or requires the approach - a component or sub-component activity, a cost line, a results indicator / DLI, a covenant or prior action, or implementation progress reported for this project.
- "mentioned": the approach appears but not as this project's own activity. Choose the closest reason:
    future_plan            - a later phase, a follow-on project, "will be considered", "may explore", "in the medium term"
    aspiration_or_vision   - government vision, strategy, expectations, hopes, general benefits of the technology
    other_program          - another project, donor, agency or programme does it; country or sector background
    lesson_or_reference    - lessons learned, international experience, best practice cited as justification
    option_considered      - alternatives weighed in design but not selected or not financed
    parent_or_prior        - built under a parent or earlier project; this project does not finance its expansion
    unclear                - the text does not allow a judgement
- If the project applies it in a narrower form than the sentence suggests, still answer "applied" and say so in the reason.
- Re-state the evidence level you would give the marked sentence after reading the context (L1 Referenced, L2 Planned, L3 Implemented).

Return JSON:
{"adoption": "applied" | "mentioned", "mention_for": "future_plan" | "aspiration_or_vision" | "other_program" | "lesson_or_reference" | "option_considered" | "parent_or_prior" | "unclear" | "",
 "evidence_level": "L2", "confidence": 0.8, "reason": "one or two sentences quoting the decisive words"}

=== TEXT (verbatim; the marked sentence is between >>> and <<<) ===
{{context}}
