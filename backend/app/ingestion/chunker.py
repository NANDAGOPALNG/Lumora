"""Deterministic, paragraph-aware chunking with configurable size/overlap.

This is structure-aware chunking (paragraphs, word boundaries) - not
semantic chunking via an LLM or embedding model.
"""

import re
from typing import List


def split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_long_paragraph(paragraph: str, max_size: int) -> List[str]:
    """Split a paragraph that exceeds max_size into word-bounded pieces."""
    words = paragraph.split()
    pieces: List[str] = []
    current: List[str] = []
    current_len = 0

    for word in words:
        added_len = len(word) + (1 if current else 0)
        if current and current_len + added_len > max_size:
            pieces.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += added_len

    if current:
        pieces.append(" ".join(current))

    return pieces


def _overlap_tail(text: str, overlap_size: int) -> str:
    """Return up to the last overlap_size chars of text, trimmed to a word boundary."""
    if overlap_size <= 0 or not text:
        return ""

    tail = text[-overlap_size:]
    space_idx = tail.find(" ")
    if space_idx != -1:
        tail = tail[space_idx + 1 :]
    return tail.strip()


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Split cleaned text into overlapping, paragraph-aware chunks.

    Paragraphs are packed together up to chunk_size; a paragraph longer
    than chunk_size is first safely split at word boundaries. Adjacent
    chunks share up to chunk_overlap characters of trailing context
    (trimmed to a word boundary), except where that would push a chunk
    over chunk_size - overlap is preserved where possible, not guaranteed.

    Never splits a word, never returns an empty chunk.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    units: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
        else:
            units.extend(_split_long_paragraph(paragraph, chunk_size))

    chunks: List[str] = []
    current = ""

    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap = _overlap_tail(current, chunk_overlap)
            current = f"{overlap}\n\n{unit}" if overlap else unit
            if len(current) > chunk_size:
                # Overlap plus the new unit doesn't fit - drop the overlap
                # rather than exceed chunk_size or split the unit's words.
                current = unit
        else:
            current = unit

    if current.strip():
        chunks.append(current)

    return [c for c in chunks if c.strip()]
