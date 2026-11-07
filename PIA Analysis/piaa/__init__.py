"""PIA Analysis (``piaa``) - Project Innovation Approach Analysis.

The package answers one question for a World Bank Group lending project:
*does the project adopt an innovative (Digital & AI) approach, and if so,
which approaches, how are they classified, and are they replicated elsewhere
in the portfolio?*

Public surface (stable for the web app and the notebook):

- :func:`piaa.runner.run_project`   - run a workflow on one project (single-record test API)
- :func:`piaa.runner.run_batch`     - run a workflow on many projects with caching
- :func:`piaa.workflows.list_workflows` - discover workflow versions
- :mod:`piaa.export`                - write the two output tables (projects, approaches)
"""

from .config import Settings
from .runner import run_project, run_batch
from .workflows import list_workflows, load_workflow

__all__ = ["Settings", "run_project", "run_batch", "list_workflows", "load_workflow"]
__version__ = "0.3.31"
