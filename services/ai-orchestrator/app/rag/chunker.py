"""
Semantic chunker — splits documents into overlapping chunks
bounded by sentence/paragraph boundaries.

Strategy:
1. Split on paragraph boundaries first.
2. If a paragraph exceeds max_chunk_chars, split further at sentences.
3. Apply overlap so that context is not lost across chunk boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Sentence boundary detection: end-of-sentence punctuation followed by whitespace
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_PARA_BOUNDARY = re.compile(r"\n{2,}")


@dataclass
class Chunk:
    text: str
    chunk_index: int
    char_start: int
    char_end: int
    metadata: dict[str, str | int]


def _split_sentences(text: str) -> list[str]:
    parts = _SENT_BOUNDARY.split(text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(
    text: str,
    max_chunk_chars: int = 1200,
    overlap_chars: int = 150,
    metadata: dict[str, str | int] | None = None,
) -> list[Chunk]:
    """
    Split *text* into overlapping semantic chunks.

    Args:
        text: Raw document text (already cleaned/normalised).
        max_chunk_chars: Maximum characters per chunk.
        overlap_chars: Character overlap between adjacent chunks.
        metadata: Base metadata to attach to every chunk.

    Returns:
        List of Chunk objects ordered by position.
    """
    base_meta = metadata or {}
    paragraphs = _PARA_BOUNDARY.split(text)
    sentences: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chunk_chars:
            sentences.append(para)
        else:
            sentences.extend(_split_sentences(para))

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_len: int = 0
    chunk_idx: int = 0
    char_cursor: int = 0

    for sent in sentences:
        sent_len = len(sent) + 1  # +1 for space separator

        if current_len + sent_len > max_chunk_chars and current_parts:
            chunk_text_str = " ".join(current_parts)
            chunks.append(
                Chunk(
                    text=chunk_text_str,
                    chunk_index=chunk_idx,
                    char_start=char_cursor,
                    char_end=char_cursor + len(chunk_text_str),
                    metadata={**base_meta, "chunk_index": chunk_idx},
                )
            )
            chunk_idx += 1

            # Overlap: keep trailing sentences that fit within overlap_chars
            overlap_parts: list[str] = []
            overlap_len = 0
            for part in reversed(current_parts):
                if overlap_len + len(part) + 1 > overlap_chars:
                    break
                overlap_parts.insert(0, part)
                overlap_len += len(part) + 1

            char_cursor += current_len - overlap_len
            current_parts = overlap_parts
            current_len = overlap_len

        current_parts.append(sent)
        current_len += sent_len

    # Flush remaining
    if current_parts:
        chunk_text_str = " ".join(current_parts)
        chunks.append(
            Chunk(
                text=chunk_text_str,
                chunk_index=chunk_idx,
                char_start=char_cursor,
                char_end=char_cursor + len(chunk_text_str),
                metadata={**base_meta, "chunk_index": chunk_idx},
            )
        )

    return chunks
