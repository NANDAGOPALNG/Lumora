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


# --- Source-code chunking -------------------------------------------------
#
# Used only for source/config file types (see pipeline._chunk_parsed);
# prose chunking above is untouched.

# A top-level (column 0) line that starts a new declaration.
_DECLARATION_RE = re.compile(
    r"^(?:"
    r"(?:async\s+)?def\s|class\s|"                       # Python
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\b|"   # JS/TS
    r"export\s|"                                          # JS/TS exports
    r"(?:abstract\s+)?(?:interface|enum|namespace|type)\s|"    # TS
    r"(?:const|let|var)\s+\w+\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(|function\b|\w+\s*=>)|"
    r"(?:create|alter|drop)\s+\w+|"                       # SQL (case-insensitive below)
    r"(?:function\s+)?\w+\s*\(\)\s*\{|"                   # shell functions
    r"(?:@\w)"                                            # decorators
    r")",
    re.IGNORECASE,
)
# Lines that belong to the declaration that follows them.
_ATTACHED_PREFIXES = ("@", "#", "//", "/*", "*", "--")


def _declaration_starts(lines: List[str]) -> List[int]:
    """Indexes of lines where a new top-level declaration segment begins,
    including any decorator/comment lines directly above it."""
    starts: List[int] = []
    for i, line in enumerate(lines):
        if not line or line[0] in " \t" or not _DECLARATION_RE.match(line):
            continue
        # A decorator directly followed by its def/class: only the
        # decorator line (the first of the run) starts the segment.
        if i > 0 and lines[i - 1].startswith("@"):
            continue
        j = i
        while j > 0 and lines[j - 1].strip() and lines[j - 1].lstrip().startswith(_ATTACHED_PREFIXES) and lines[j - 1][0] not in " \t":
            j -= 1
        if starts and j <= starts[-1]:
            continue
        starts.append(j)
    return starts


def _hard_split(text: str, max_size: int) -> List[str]:
    return [text[i : i + max_size] for i in range(0, len(text), max_size)]


def _split_oversized(segment: str, max_size: int) -> List[str]:
    """Split a segment longer than max_size at blank lines, then at line
    boundaries; a single over-long line is cut at max_size characters."""
    pieces: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            pieces.append(current)
        current = ""

    for line in segment.split("\n"):
        if len(line) > max_size:
            flush()
            pieces.extend(p for p in _hard_split(line, max_size) if p.strip())
            continue
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_size:
            flush()
            current = line
        else:
            current = candidate
    flush()
    return pieces


def chunk_code(text: str, chunk_size: int) -> List[str]:
    """Split source code into chunks of at most chunk_size characters,
    preferring to break between top-level functions/classes so a
    declaration is not cut in half unless it alone exceeds chunk_size.

    Indentation and line structure are preserved. No overlap is added:
    chunks begin at declaration boundaries, so repeating trailing text
    would only duplicate code.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not text.strip():
        return []

    lines = text.split("\n")
    starts = _declaration_starts(lines)
    bounds = ([0] if not starts or starts[0] != 0 else []) + starts + [len(lines)]

    segments: List[str] = []
    for begin, end in zip(bounds, bounds[1:]):
        segment = "\n".join(lines[begin:end]).strip("\n")
        if segment.strip():
            segments.append(segment)

    units: List[str] = []
    for segment in segments:
        if len(segment) <= chunk_size:
            units.append(segment)
        else:
            units.extend(_split_oversized(segment, chunk_size))

    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = unit
    if current.strip():
        chunks.append(current)

    return [c for c in chunks if c.strip()]
