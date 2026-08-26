"""Deterministic text cleaning/normalization.

No LLM, no summarization, no content rewriting - only whitespace and
line-ending normalization that preserves paragraph structure and
content semantics.
"""

import re


def clean_text(text: str) -> str:
    """Normalize line endings and whitespace while preserving paragraph boundaries."""
    if not text:
        return ""

    # Normalize line endings (CRLF/CR -> LF).
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Trailing whitespace on a line is never meaningful.
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))

    # Collapse 3+ consecutive blank lines down to one blank line (a single
    # paragraph break) without merging separate paragraphs together.
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    # Collapse runs of horizontal whitespace, but never touch newlines -
    # that's what keeps paragraph/line boundaries intact.
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)

    return normalized.strip()
