# Methodology Note 3: Adoption (applied vs mentioned) and Replication verification

Workflow **v3** = v2 (DDAT sentence coding, Notes 1 & 2) + two review dimensions that the first full read of v2 output showed to be necessary.

## 1. Why: coded is not the same as adopted

Reading one or two pages of context around v2's coded sentences showed that a sentence can match a DDAT approach while the project does **not** adopt it. Recurring cases:

| Pattern | Example wording | v2 outcome |
| --- | --- | --- |
| Future phase or follow-on operation | "will be considered in a second phase", "may explore" | often L2 |
| Government vision, strategy, expectations | "the Government envisions a digital economy", "digital tools can improve" | L1 or L2 |
| Another programme, donor or agency; background | "the EU-financed programme has deployed", "the Ministry launched" | L1 |
| Lessons or international experience cited as justification | "experience from Kenya shows", "lessons from the previous project" | L1 |
| Options weighed in design but not financed | "an alternative would be" | L2 |
| Built under a parent or earlier project | "developed under the parent project", "existing system will be used" | L1/L2 |

The sentence-level evidence level (L1 Referenced / L2 Planned / L3 Implemented) catches part of this, but not when the sentence itself reads like a plan. v3 therefore makes **adoption** an explicit, context-based decision.

## 2. Adoption step (after aggregation)

For every project × DDAT approach:

1. Take the strongest coded sentence (highest evidence level; PAD before ISR).
2. Rebuild about one page (~3,200 characters) of the source document around it, with paragraph structure restored and the sentence marked.
3. The model decides **applied** or **mentioned** and, for mentioned, one reason category: `future_plan`, `aspiration_or_vision`, `other_program`, `lesson_or_reference`, `option_considered`, `parent_or_prior`, `unclear`. It also re-states the evidence level after reading the context and gives a confidence; "applied" below 0.5 confidence is downgraded.
4. Approach status: `validated` (applied and L2/L3) · `mentioned_only` · `referenced_only` (L1 only). **Headline counts use `validated` only.** Mentioned approaches stay in the database with their reason, so "mention without adoption" can be reported by project, sector and theme. A project with 20 mentioned sentences and no applied approach counts as *not* adopting.
5. Database and exports carry `adoption`, `mention_for`, `adoption_reason` per approach and `n_mentioned_only` per project; the reviewer can override both in the web app (every change logged with a reason).

## 3. Replication column: detection and verification

1. **Explicit reference** - other in-scope project IDs (P-codes) or names (≥3 words) found in the project's documents; score 0.9 / 0.8 when within ±300 characters of replication language (builds on, replicates, scaled from, lessons from, parent project, additional financing, modelled on, second phase …), else 0.5 / 0.4. The passage is stored as evidence.
2. **Similar approach** - TF-IDF cosine similarity between the approach text (DDAT name + coded sentences) and every approach of other projects already in the portfolio store; links ≥ 0.30 kept (max 5), with the matched approach id and score. Incremental; a final rescan refreshes links once the portfolio is complete.
3. **Direction** - by approval date: earlier project = origin (`replicated_by`), later = `replicates`.
4. **Verification** - the web app shows, side by side, this project's evidence in page context and the other project's matching evidence (or the explicit-reference passage with the P-code highlighted), with a jump to the other project. The reviewer records `confirmed` / `rejected` / `unsure` with a note; stored as `replication_verdict` and exported.

## 4. Reviewer tooling added in this version

* **Review in context** - for any evidence sentence, rebuild 1-6 pages of the source document on demand, formatted (headings, numbered paragraphs, sub-points), with the evidence, other coded sentences and approach keywords highlighted and aspiration / commitment wording flagged per paragraph.
* **Workflow page** - flowchart of each version (Python vs LLM steps, data in/out); click a step to see its code and prompt files; comparison report between any two versions (steps, prompts, config diff, results in the database).
* **Language toggle** (English / 中文) for the interface chrome; data stays English.

## 5. Quality control

Unchanged from Note 1: run twice (Run A / Run B), compare rows on (document, sentence position, approach code), flag disagreements, spot-check 5% of agreed rows, report agreement per approach. v2's Run A / Run B gave 51% row-level agreement and 0.74 Jaccard at project × approach level; the adoption step and the reviewer tooling are the response to that result - headline figures should be read at project × approach level after review, not at sentence level.
