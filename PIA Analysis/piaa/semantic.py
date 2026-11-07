"""Semantic candidate matching (Methodology Note 1, step 3).

Each sentence is compared with each DDAT approach's definition + typical
examples. Two backends:

* ``sentence-transformers`` (``all-MiniLM-L6-v2`` by default) when the package
  and model are available locally - true embedding similarity;
* a TF-IDF cosine fallback (scikit-learn) otherwise - weaker, but keyword-free,
  so it still surfaces sentences that use different wording.

The backend actually used is recorded in the run trace so results are
interpretable. Thresholds are set per backend in the workflow config.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .taxonomy import ddat


@dataclass
class SemanticMatcher:
    backend: str
    threshold: float
    _model: object = None
    _theme_vecs: object = None
    _codes: list[str] = None
    _tfidf: object = None

    @classmethod
    def build(cls, prefer: str = "auto", threshold_embedding: float = 0.45, threshold_tfidf: float = 0.18, model_name: str = "all-MiniLM-L6-v2"):
        codes = list(ddat.approaches().keys())
        texts = [ddat.theme_text(c) for c in codes]
        if prefer in ("auto", "embedding"):
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(model_name)
                vecs = model.encode(texts, normalize_embeddings=True)
                return cls("embedding:" + model_name, threshold_embedding, model, vecs, codes)
            except Exception:
                if prefer == "embedding":
                    raise
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        vecs = vec.fit_transform(texts)
        return cls("tfidf", threshold_tfidf, None, vecs, codes, vec)

    def scores(self, sentences: list[str]) -> np.ndarray:
        """(n_sentences, n_codes) similarity matrix."""
        if not sentences:
            return np.zeros((0, len(self._codes)))
        if self.backend.startswith("embedding"):
            s = self._model.encode(sentences, normalize_embeddings=True, batch_size=64)
            return s @ self._theme_vecs.T
        from sklearn.metrics.pairwise import cosine_similarity
        return cosine_similarity(self._tfidf.transform(sentences), self._theme_vecs)

    def candidates(self, sentences: list[str]) -> list[dict[str, float]]:
        """Per sentence: {code: score} for codes above the threshold."""
        m = self.scores(sentences)
        out = []
        for row in m:
            out.append({self._codes[j]: float(round(row[j], 3)) for j in np.where(row >= self.threshold)[0]})
        return out
