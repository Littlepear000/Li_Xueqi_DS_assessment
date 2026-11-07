# Why This Package Is Called "PIA Analysis"

**PIA** stands for **P**roject **I**nnovation **A**pproach.

`PIA Analysis` is the root directory of the code package that supports the
*Project Innovation Approach Analysis* work for the World Bank Group (WBG)
portfolio. It replaces the former `SRC` folder as the single home for all
source code, configuration, and developer documentation of this project.

## Rationale

1. **It names the subject, not the tool.**
   The package exists to analyse *how* WBG projects approach innovation
   (in particular digital and AI innovation), using the project list in
   `raw_data/projects.csv`, local project documents, and data pulled from
   online APIs. "Project Innovation Approach" is the exact analytical
   question the package answers; "Analysis" states what the package does
   with it.

2. **It is not tied to a single data source or institution.**
   The name deliberately omits "WBG" and omits any specific API or document
   type. Project IDs are the only join key between sources, so new sources
   (additional APIs, more local documents, a refreshed `projects.csv`) can be
   added without the name becoming misleading.

3. **It yields a clean Python identifier.**
   The human-readable folder name is `PIA Analysis`. The importable Python
   package inside it is `piaa` (lower-case acronym of the four words),
   which follows PEP 8 package naming (short, all lower-case, no
   underscores) and gives a concise command-line entry point
   (for example `piaa sync`, `piaa analyze`).

4. **It stays readable for non-developers.**
   Reviewers who open the repository see "PIA Analysis" and can infer the
   purpose immediately; the acronym is expanded here and in the package
   docstring so the meaning is never lost.

## Naming Conventions Inside the Package

| Item | Name | Note |
| --- | --- | --- |
| Root directory | `PIA Analysis/` | Human-readable; contains everything |
| Python package | `piaa` | Import name and CLI command |
| Project join key | `project_id` | Matches `projects.csv` and document file names |

## Language Policy

All files under `PIA Analysis/` — source code, comments, docstrings,
configuration, and documentation — are written in **English**.
