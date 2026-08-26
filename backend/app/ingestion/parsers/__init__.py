"""Format-specific document parsers.

Each parser extracts raw text (grouped into pages where the format has
a natural page concept) - no cleaning or chunking happens here. See
`app.ingestion.cleaner` and `app.ingestion.chunker` for those steps.
"""

from app.ingestion.parsers import docx_parser, markdown_parser, pdf_parser, txt_parser
from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError

_PARSERS = {
    "pdf": pdf_parser.parse,
    "docx": docx_parser.parse,
    "txt": txt_parser.parse,
    "md": markdown_parser.parse,
}


def parse(file_path: str, file_type: str) -> ParsedDocument:
    """Parse a document file according to its type.

    Raises:
        ParsingError: if file_type isn't supported, the file can't be
            read, or it contains no extractable text.
    """
    parser = _PARSERS.get(file_type.lower())
    if parser is None:
        raise ParsingError(f"Unsupported document type for ingestion: {file_type!r}")
    return parser(file_path)


__all__ = ["parse", "ParsedDocument", "ParsedPage", "ParsingError"]
