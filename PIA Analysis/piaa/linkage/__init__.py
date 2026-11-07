"""Replication and scaling links between approaches (Methodology Note 3).

Entry point: :func:`piaa.linkage.pipeline.build_links`, which reads the latest
review database, scans the project documents for replication / scaling cues,
attaches them to approaches, asks the model to confirm each attachment and
writes the **Approach Link Table** plus family, QC and summary tables.

Modules
-------
cues      cue lists (Note 3 Appendix), cue scan, alias index for source resolution
families  project families (AF / restructuring / phases / series) from metadata and documents
pipeline  the six identification steps, run A / run B QC, outputs
"""
from .pipeline import build_links  # noqa: F401
