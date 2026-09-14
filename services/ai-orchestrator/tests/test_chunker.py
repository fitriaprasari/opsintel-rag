"""
Unit tests for the semantic chunker.
"""
from __future__ import annotations

import pytest

from app.rag.chunker import chunk_text


class TestChunkText:
    def test_short_text_produces_single_chunk(self):
        text = "This is a short document. It fits in one chunk."
        chunks = chunk_text(text, max_chunk_chars=500)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert "short document" in chunks[0].text

    def test_long_text_splits_into_multiple_chunks(self):
        # 5 paragraphs, each ~300 chars, max=200 should split them
        para = "A" * 50 + ". " + "B" * 50 + ". " + "C" * 50 + ". " + "D" * 50 + "."
        text = "\n\n".join([para] * 5)
        chunks = chunk_text(text, max_chunk_chars=200, overlap_chars=30)
        assert len(chunks) > 1

    def test_chunk_indexes_are_sequential(self):
        text = " ".join(["Word" + str(i) + "." for i in range(200)])
        chunks = chunk_text(text, max_chunk_chars=100)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_metadata_is_attached_to_every_chunk(self):
        text = "Hello world. This is a test document."
        meta = {"service_name": "test-service", "environment": "test"}
        chunks = chunk_text(text, metadata=meta)
        for c in chunks:
            assert c.metadata["service_name"] == "test-service"
            assert c.metadata["environment"] == "test"

    def test_empty_text_returns_empty_list(self):
        chunks = chunk_text("")
        assert chunks == []

    def test_whitespace_only_returns_empty_list(self):
        chunks = chunk_text("   \n\n   ")
        assert chunks == []

    def test_no_overlap_when_overlap_zero(self):
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        chunks = chunk_text(text, max_chunk_chars=30, overlap_chars=0)
        # Verify no duplicate content between adjacent chunks
        for i in range(len(chunks) - 1):
            assert chunks[i].text != chunks[i + 1].text
