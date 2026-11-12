"""DOCX paragraph extraction.

Extracts paragraphs in document order; embedded images are ignored.
DOCX has no reliable page boundaries without rendering the layout, so
the whole document is treated as a single page.
"""

from io import BytesIO

from docx import Document as DocxDocument

from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError


def parse(file_path: str) -> ParsedDocument:
    try:
        docx_document = DocxDocument(file_path)
    except Exception as exc:
        raise ParsingError(f"Could not read DOCX file: {exc}") from exc

    return _parse_document(docx_document)


def parse_bytes(content: bytes) -> ParsedDocument:
    """Parse already-loaded file content (e.g. downloaded from object storage)."""
    try:
        docx_document = DocxDocument(BytesIO(content))
    except Exception as exc:
        raise ParsingError(f"Could not read DOCX file: {exc}") from exc

    return _parse_document(docx_document)


def _parse_document(docx_document) -> ParsedDocument:
    paragraphs = [p.text for p in docx_document.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)

    if not text.strip():
        raise ParsingError("DOCX contains no extractable text")

    return ParsedDocument(pages=[ParsedPage(text=text, page_number=None)])
