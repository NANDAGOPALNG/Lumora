"""PDF text extraction.

Extracts text per page (no OCR - a page with no embedded/extractable
text stays empty rather than being guessed at).
"""

from io import BytesIO

from pypdf import PdfReader

from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError


def parse(file_path: str) -> ParsedDocument:
    try:
        reader = PdfReader(file_path)
    except Exception as exc:
        raise ParsingError(f"Could not read PDF file: {exc}") from exc

    return _parse_reader(reader)


def parse_bytes(content: bytes) -> ParsedDocument:
    """Parse already-loaded file content (e.g. downloaded from object storage)."""
    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise ParsingError(f"Could not read PDF file: {exc}") from exc

    return _parse_reader(reader)


def _parse_reader(reader: PdfReader) -> ParsedDocument:
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            # A single unparsable page shouldn't abort the whole document -
            # it just contributes no text.
            text = ""
        pages.append(ParsedPage(text=text, page_number=page_number))

    if not any(page.text.strip() for page in pages):
        raise ParsingError(
            "PDF contains no extractable text (it may be a scanned/image-only "
            "document; OCR is not supported)"
        )

    return ParsedDocument(pages=pages)
