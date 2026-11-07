# Workflow v2

- 2026-11-06  Rebuilt on Methodology Note 1 (approach definition and coding rules) and Note 2 (category mapping).
  - An approach is one of the 21 DDAT second-level themes (250100-251300, 270100-270800), coded sentence by sentence.
  - Steps: segment -> keyword match -> semantic match -> LLM classify (code, evidence level L1/L2/L3, status, reason) -> exclusions -> AEC rows.
  - Project-level approaches aggregate the rows (highest evidence level); headline counts use L2/L3.
  - Category = pillar via solution: direct mapping where the approach has one candidate solution, model choice otherwise (Note 2).
  - Sector is a project attribute (lead sector from projects.csv); theme = the approach's parent theme.
  - Speed: 16 parallel projects, batched classification with the taxonomy in a cached system prompt, 4 concurrent batches per project.
  - Quality control: `piaa compare` flags differences between two runs (Run A / Run B) and samples 5% of agreed rows.

- **v2.0** 2026-11-06  First tagged state (version tags introduced in piaa 0.2.0).
