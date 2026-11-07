# Pattern workflow r2

- 2026-11-06 - new design agreed with the project lead:
  1. semantic match on each approach's theme + the original text it was extracted from;
  2. sector and category are supporting signals (small bonus), never a requirement;
  3. pairs above the threshold are verified by the model after reading about two pages before and after
     both evidence sentences in the source documents;
  4. a verified pair is the same approach;
  5. same approach in projects of different countries = replication, of the same country = scaling.
  Replaces r1's weighted name/description/theme score and the provisional scaling definition.
  Embedding backend (sentence-transformers) is used when installed; TF-IDF fallback also reads the approach
  name and description because lexical matching on evidence alone cannot find paraphrases.
  Verdicts are cached so re-runs only pay for new pairs.

- **r2.0** 2026-11-06  First tagged state (version tags introduced in piaa 0.2.0).
