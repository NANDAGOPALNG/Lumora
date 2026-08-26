"""Plain text (.txt) reading."""

from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError


def parse(file_path: str) -> ParsedDocument:
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParsingError(f"File is not valid UTF-8 text: {exc}") from exc
    except OSError as exc:
        raise ParsingError(f"Could not read text file: {exc}") from exc

    if not text.strip():
        raise ParsingError("Text file is empty")

    return ParsedDocument(pages=[ParsedPage(text=text, page_number=None)])
