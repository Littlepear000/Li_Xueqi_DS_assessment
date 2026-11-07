## Approach under review
- approach_id: {{approach_id}} | project {{project_id}} ({{country}}, FY{{fy}}, sector: {{sector}}) - {{project_name}}
- name: {{name}}
- description: {{description}}
- category: {{category}}

### Passages from the project's documents ({{n_passages}})
{{passages}}

### Signals found by rules
- replication language in the passages: {{rep_cues}}
- scaling language in the passages: {{sca_cues}}
- other projects named in the passages (P-code - name - country - approved): {{named_refs}}
- explicit references in the FULL documents (other P-codes found next to replication language when the approach was extracted; the sentence is quoted): {{explicit_refs}}

## Candidate EARLIER approaches of other projects (semantic matches - some will be unrelated)
{{candidates}}

## Tasks
A. Replication level: "confirmed", "likely" or "none" (definitions in the system prompt).
   - source_project_id: P-code of the earlier project (from passages, references or candidates), or "".
   - source_text: the source as written ("the Niger Smart Villages project", "previous World Bank operations in the region"), or "".
   - source_candidate_id: the candidate that is the source, or the closest same / similar approach from the source project, or "".
   - source_quote: verbatim span carrying the replication statement, or "".
B. For EVERY candidate: same (true when confidence >= 0.5), confidence per the grading scale, shared_solution in a few words, one-line reason.

Return JSON:
{"replication": {"level": "confirmed|likely|none", "source_project_id": "", "source_text": "", "source_candidate_id": "",
                 "source_quote": "", "reason": ""},
 "candidates": [{"candidate_id": "...", "same": true, "confidence": 0.0, "shared_solution": "", "reason": ""}]}
