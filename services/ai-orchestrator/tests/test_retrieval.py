"""
Unit tests for the RRF fusion algorithm.
"""
from __future__ import annotations

import pytest

from app.rag.retrieval import _reciprocal_rank_fusion, _to_retrieved_document


class TestRRF:
    def _make_result(self, doc_id: str, score: float, title: str = "Test Doc"):
        return {
            "id": doc_id,
            "score": score,
            "payload": {
                "content": f"Content for {doc_id}",
                "title": title,
                "source_type": "runbook",
            },
        }

    def test_fusion_deduplicates(self):
        dense = [self._make_result("doc-1", 0.9), self._make_result("doc-2", 0.8)]
        sparse = [self._make_result("doc-1", 0.7), self._make_result("doc-3", 0.6)]
        fused = _reciprocal_rank_fusion(dense, sparse, top_k=10)
        ids = [r["id"] for r in fused]
        assert len(ids) == len(set(ids))  # no duplicates

    def test_document_in_both_lists_ranks_higher(self):
        dense = [self._make_result("doc-shared", 0.9), self._make_result("doc-only-dense", 0.8)]
        sparse = [self._make_result("doc-shared", 0.7), self._make_result("doc-only-sparse", 0.6)]
        fused = _reciprocal_rank_fusion(dense, sparse, top_k=10)
        # doc-shared should rank first (appears in both)
        assert fused[0]["id"] == "doc-shared"

    def test_top_k_respected(self):
        dense = [self._make_result(f"d{i}", 0.9 - i * 0.1) for i in range(10)]
        sparse = [self._make_result(f"s{i}", 0.9 - i * 0.1) for i in range(10)]
        fused = _reciprocal_rank_fusion(dense, sparse, top_k=5)
        assert len(fused) <= 5

    def test_empty_lists_return_empty(self):
        fused = _reciprocal_rank_fusion([], [])
        assert fused == []

    def test_only_dense_results(self):
        dense = [self._make_result("doc-1", 0.9), self._make_result("doc-2", 0.8)]
        fused = _reciprocal_rank_fusion(dense, [])
        assert len(fused) == 2

    def test_rrf_scores_are_present(self):
        dense = [self._make_result("doc-1", 0.9)]
        fused = _reciprocal_rank_fusion(dense, [])
        assert "rrf_score" in fused[0]
        assert fused[0]["rrf_score"] > 0

    def test_to_retrieved_document_conversion(self):
        result = {
            "id": "chunk-abc",
            "rrf_score": 0.75,
            "payload": {
                "content": "Restart the service.",
                "title": "Order Service Runbook",
                "source_type": "runbook",
                "service_name": "order-service",
            },
        }
        doc = _to_retrieved_document(result)
        assert doc.document_id == "chunk-abc"
        assert doc.title == "Order Service Runbook"
        assert doc.score == 0.75
        assert "Restart" in doc.chunk_text
        assert doc.metadata["service_name"] == "order-service"
        assert "access_policy" not in doc.metadata
