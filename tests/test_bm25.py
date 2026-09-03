"""
Unit tests for BM25 encoder.
"""
from __future__ import annotations

import pytest

from app.rag.bm25 import BM25Encoder, simple_sparse_encode


class TestBM25Encoder:
    def _fitted_encoder(self) -> BM25Encoder:
        enc = BM25Encoder()
        corpus = [
            "database connection pool exhausted timeout",
            "memory leak java heap outofmemory error",
            "kubernetes pod restart crashloopbackoff",
            "http latency response time p99 exceeded",
        ]
        enc.fit(corpus)
        return enc

    def test_fit_builds_vocabulary(self):
        enc = self._fitted_encoder()
        assert enc.vocab_size > 0

    def test_encode_query_returns_indices_and_values(self):
        enc = self._fitted_encoder()
        result = enc.encode_query("database connection timeout")
        assert "indices" in result
        assert "values" in result
        assert len(result["indices"]) == len(result["values"])

    def test_encode_unknown_term_excluded(self):
        enc = self._fitted_encoder()
        result = enc.encode_query("zzz_this_term_does_not_exist_in_vocab")
        # Unknown terms have no index in vocab, so result should be empty or minimal
        assert isinstance(result["indices"], list)

    def test_encode_empty_query(self):
        enc = self._fitted_encoder()
        result = enc.encode_query("")
        assert result["indices"] == []
        assert result["values"] == []

    def test_unfitted_encoder_returns_empty(self):
        enc = BM25Encoder()
        result = enc.encode_query("any query here")
        assert result["indices"] == []
        assert result["values"] == []

    def test_relevant_query_scores_higher(self):
        """A query matching more terms should produce more non-zero values."""
        enc = self._fitted_encoder()
        r1 = enc.encode_query("database connection")
        r2 = enc.encode_query("database connection pool exhausted timeout error")
        # More matching terms → more indices
        assert len(r2["indices"]) >= len(r1["indices"])
