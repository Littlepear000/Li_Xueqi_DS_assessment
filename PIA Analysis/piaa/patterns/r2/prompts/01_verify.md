Decide whether project A and project B use the same approach.
Sector and category are given for reference only; they do not need to match.

## Approach A
- project: {{project_a}} ({{country_a}}, FY{{fy_a}}) - {{project_name_a}}
- approach name: {{name_a}}
- theme: {{theme_a}}
- sector: {{sector_a}} | category: {{category_a}}
- evidence ({{doc_a}}), marked with >>> <<< in the context below:
{{context_a}}

## Approach B
- project: {{project_b}} ({{country_b}}, FY{{fy_b}}) - {{project_name_b}}
- approach name: {{name_b}}
- theme: {{theme_b}}
- sector: {{sector_b}} | category: {{category_b}}
- evidence ({{doc_b}}), marked with >>> <<< in the context below:
{{context_b}}

Return JSON:
{"same": true | false,
 "confidence": 0.0-1.0,
 "shared_solution": "<the common approach in a few words, or empty>",
 "difference": "<main difference, or empty>",
 "reason": "<one or two sentences citing both contexts>"}
