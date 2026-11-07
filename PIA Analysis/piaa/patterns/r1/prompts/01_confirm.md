Decide whether approach A and approach B are the same approach.

Approach A ({{project_a}}, FY{{fy_a}}, {{country_a}})
- name: {{name_a}}
- theme: {{theme_a}}
- evidence: "{{evidence_a}}"

Approach B ({{project_b}}, FY{{fy_b}}, {{country_b}})
- name: {{name_b}}
- theme: {{theme_b}}
- evidence: "{{evidence_b}}"

Return JSON: {"same": true|false, "confidence": 0.0-1.0, "reason": "<one sentence>"}
