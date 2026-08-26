"""Markdown (.md) reading.

Reads the raw Markdown text as-is (headings, lists, emphasis markers,
etc. are preserved as plain text) - it is never converted to HTML.
"""

from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError


def parse(file_path: str) -> ParsedDocument:
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParsingError(f"File is not valid UTF-8 text: {exc}") from exc
    except OSError as exc:
        raise ParsingError(f"Could not read Markdown file: {exc}") from exc

    if not text.strip():
        raise ParsingError("Markdown file is empty")

    return ParsedDocument(pages=[ParsedPage(text=text, page_number=None)])
