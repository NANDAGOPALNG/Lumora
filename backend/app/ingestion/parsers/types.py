"""Shared types for document parsers."""

from dataclasses import dataclass, field
from typing import List, Optional


class ParsingError(Exception):
    """Raised when a document's text cannot be extracted."""


@dataclass
class ParsedPage:
    """A single page (or the whole document, if the format has no page concept)."""

    text: str
    page_number: Optional[int] = None


@dataclass
class ParsedDocument:
    pages: List[ParsedPage] = field(default_factory=list)
