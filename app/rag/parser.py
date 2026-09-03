"""
Document parser — extracts plain text from various input formats.
Supported: plain text, markdown, HTML, PDF (via pdfplumber if installed).
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

# HTML tag stripper
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE_NORM = re.compile(r"\n{3,}")
_SPACE_NORM = re.compile(r" {2,}")


def _strip_html(text: str) -> str:
    text = _HTML_TAG.sub(" ", text)
    return text


def _normalise_whitespace(text: str) -> str:
    text = _WHITESPACE_NORM.sub("\n\n", text)
    text = _SPACE_NORM.sub(" ", text)
    return text.strip()


def parse_text(content: str, content_type: str = "text/plain") -> str:
    """
    Extract and normalise plain text from raw content.

    Args:
        content: Raw file content as string.
        content_type: MIME type hint (text/plain, text/html, text/markdown).

    Returns:
        Normalised plain text string.
    """
    if content_type in ("text/html", "application/xhtml+xml"):
        content = _strip_html(content)
    # Markdown — strip minimal formatting markers while preserving structure
    elif content_type in ("text/markdown", "text/x-markdown"):
        # Remove markdown heading markers but keep text
        content = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
        # Remove bold/italic markers
        content = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", content)
        content = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", content)
        # Remove inline code
        content = re.sub(r"`{1,3}[^`]*`{1,3}", "", content)
        # Remove links but keep label
        content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)

    return _normalise_whitespace(content)


def compute_content_hash(content: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
