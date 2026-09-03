"""
Unit tests for the document parser.
"""
from __future__ import annotations

import pytest

from app.rag.parser import compute_content_hash, parse_text


class TestParseText:
    def test_plain_text_passthrough(self):
        text = "Hello world.\n\nSecond paragraph."
        result = parse_text(text, "text/plain")
        assert "Hello world." in result
        assert "Second paragraph." in result

    def test_html_strips_tags(self):
        html = "<h1>Title</h1><p>Body text here.</p><script>alert('x')</script>"
        result = parse_text(html, "text/html")
        assert "<h1>" not in result
        assert "<script>" not in result
        assert "Title" in result
        assert "Body text here." in result

    def test_markdown_strips_headings(self):
        md = "# Main Title\n\n## Sub-heading\n\nNormal paragraph here."
        result = parse_text(md, "text/markdown")
        assert "#" not in result
        assert "Main Title" in result
        assert "Normal paragraph here." in result

    def test_markdown_strips_bold_markers(self):
        md = "This has **bold text** and _italic_ content."
        result = parse_text(md, "text/markdown")
        assert "**" not in result
        assert "_" not in result
        assert "bold text" in result
        assert "italic" in result

    def test_excessive_whitespace_normalised(self):
        text = "Line one.\n\n\n\n\nLine two."
        result = parse_text(text)
        assert "\n\n\n" not in result

    def test_content_hash_is_deterministic(self):
        text = "The same content always produces the same hash."
        h1 = compute_content_hash(text)
        h2 = compute_content_hash(text)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_content_hash_differs_for_different_content(self):
        assert compute_content_hash("content A") != compute_content_hash("content B")
