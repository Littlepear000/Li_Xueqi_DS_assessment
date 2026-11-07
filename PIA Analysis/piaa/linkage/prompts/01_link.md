PROJECT: {{project_id}} - {{project_name}} | country: {{country}} | approved: {{approval_date}}

DDAT APPROACH CODES (use exactly one per approach, or "NONE" if no digital element):
{{ddat_codes}}

APPROACHES OF THIS PROJECT (id | name | description | strongest evidence sentence):
{{approaches}}

TASK A - Give each approach above its DDAT code.

TASK B - For each CUE below decide:
- approach_ids: which of this project's approaches the cue is about (subset of the candidate ids shown; [] if it is about the project in general or about something else).
- link_type: "replication", "scaling" or "none" (see definitions).
- source_relation: where the earlier use sits:
    "this_project"   - the same project (its own roll-out, its AF or restructuring),
    "same_family"    - an earlier phase / parent / predecessor in the same series or MPA,
    "other_family"   - a different project, programme or country,
    "unspecified"    - no source mentioned.
- source_text: the source as written (project name, P-code, "country + programme"), or "" if none.
- source_named: true if source_text identifies a specific project or programme; false for generic wording ("other countries", "previous projects").
- form_hint: for scaling only: "additional_financing", "series" or "expansion_in_project"; otherwise null.
- reason: one short sentence.

CUES:
{{cues}}

TASK C - For each FAMILY CANDIDATE below (another P-code mentioned next to family language) say how that project relates to THIS project:
- "this_is_af_of"          - this project is an AF / restructuring of it
- "af_of_this"             - it is an AF / restructuring of this project
- "earlier_phase"          - it is an earlier phase / predecessor in the same series or MPA as this project
- "later_phase"            - it is a later phase / successor in the same series or MPA
- "unrelated"              - anything else (other programme, co-financing, coordination, lessons only)

FAMILY CANDIDATES:
{{family_candidates}}

Return JSON:
{"approach_codes": [{"approach_id": "...", "code": "250600"}],
 "cues": [{"cue_id": "...", "approach_ids": ["..."], "link_type": "replication|scaling|none", "source_relation": "this_project|same_family|other_family|unspecified", "source_text": "...", "source_named": true, "form_hint": null, "reason": "..."}],
 "family": [{"pcode": "P123456", "relation": "earlier_phase", "reason": "..."}]}
