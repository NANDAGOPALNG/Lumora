"""Shared UTF-8 text parser for source-code, config and markup files.

One parser serves every extension in `file_types.CODE_FILE_TYPES` - the
text is returned untouched (indentation and line structure matter in
code), and binary / non-UTF-8 content is rejected rather than indexed.
"""

from app.ingestion.parsers.types import ParsedDocument, ParsedPage, ParsingError


def parse_bytes(content: bytes) -> ParsedDocument:
    if b"\x00" in content:
        raise ParsingError("File appears to be binary (contains NUL bytes)")

    try:
        # utf-8-sig drops a leading BOM, common in files saved on Windows.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParsingError(f"File is not valid UTF-8 text: {exc}") from exc

    if not text.strip():
        raise ParsingError("Source file is empty")

    return ParsedDocument(pages=[ParsedPage(text=text, page_number=None)])


def parse(file_path: str) -> ParsedDocument:
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise ParsingError(f"Could not read source file: {exc}") from exc

    return parse_bytes(raw)
