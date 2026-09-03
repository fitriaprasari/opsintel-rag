"""
BM25 sparse vector encoder for Qdrant sparse retrieval.
Uses rank_bm25 for token frequencies, converts to index/value format.
"""
from __future__ import annotations

import re
import string
from collections import Counter
from typing import Any

from rank_bm25 import BM25Okapi


def _tokenise(text: str) -> list[str]:
    """Simple whitespace + punctuation tokeniser with lowercase normalisation."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if len(t) > 1]


class BM25Encoder:
    """
    Stateful BM25 encoder.

    Workflow:
    1. Fit on a corpus of documents (or chunks) to build vocabulary.
    2. encode_query / encode_document to produce sparse {indices, values} dicts.

    For Qdrant sparse vectors, indices are vocabulary term positions and values
    are BM25 TF-IDF weights.
    """

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._bm25: BM25Okapi | None = None

    def fit(self, texts: list[str]) -> None:
        """Build vocabulary and IDF from a corpus."""
        tokenised = [_tokenise(t) for t in texts]
        self._bm25 = BM25Okapi(tokenised)
        # Build vocabulary
        all_terms: set[str] = set()
        for tokens in tokenised:
            all_terms.update(tokens)
        self._vocab = {term: idx for idx, term in enumerate(sorted(all_terms))}
        # IDF from BM25 model
        for term, idx in self._vocab.items():
            self._idf[term] = self._bm25.idf.get(term, 0.0)

    def encode_query(self, query: str) -> dict[str, list]:
        """
        Encode a query as a sparse vector aligned to the fitted vocabulary.
        Returns {"indices": [...], "values": [...]}.
        """
        tokens = _tokenise(query)
        if not tokens or not self._vocab:
            return {"indices": [], "values": []}
        freq = Counter(tokens)
        indices, values = [], []
        for term, count in freq.items():
            if term in self._vocab:
                indices.append(self._vocab[term])
                values.append(float(count) * self._idf.get(term, 0.0))
        return {"indices": indices, "values": values}

    def encode_document(self, text: str) -> dict[str, list]:
        """Encode a single document chunk as a sparse vector."""
        return self.encode_query(text)

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)


# ── Stateless single-document BM25 sparse encoding ────────────────────────────
# Used when we have no corpus to fit against (per-document TF only).

def simple_sparse_encode(text: str, vocab: dict[str, int]) -> dict[str, list]:
    """TF-based sparse encode using pre-built vocab."""
    tokens = _tokenise(text)
    freq = Counter(tokens)
    indices, values = [], []
    for term, count in freq.items():
        if term in vocab:
            indices.append(vocab[term])
            values.append(float(count))
    return {"indices": indices, "values": values}
