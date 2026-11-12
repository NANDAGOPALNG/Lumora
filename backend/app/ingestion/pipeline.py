"""Ingestion pipeline: extract -> clean -> chunk.

This module only produces in-memory chunk data from a document file on
disk, or from in-memory file content - it does not touch the database (Document/Chunk models,
repositories, services) or any API route. Wiring this into the reindex
flow and persisting Chunk rows is a separate task.
"""

from dataclasses import dataclass
from typing import List, Optional

from app.config.settings import Settings
from app.ingestion import parsers
from app.ingestion.chunker import chunk_text
from app.ingestion.cleaner import clean_text


@dataclass
class IngestedChunk:
    index: int
    text: str
    page_number: Optional[int] = None


def extract_chunks(
    file_path: str,
    file_type: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[IngestedChunk]:
    """Parse, clean, and chunk a document file.

    chunk_size/chunk_overlap default to the configured Settings values
    when not given explicitly.

    Raises:
        parsers.ParsingError: if the file's type is unsupported, it
            can't be read, or it contains no extractable text.
    """
    parsed = parsers.parse(file_path, file_type)
    return _chunk_parsed(parsed, chunk_size, chunk_overlap)


def extract_chunks_from_bytes(
    content: bytes,
    file_type: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[IngestedChunk]:
    """Parse, clean, and chunk in-memory document content.

    Identical to `extract_chunks` for a file with the same content; used
    when the document comes from object storage rather than a local path.

    Raises:
        parsers.ParsingError: if the type is unsupported, the content
            can't be read, or it contains no extractable text.
    """
    parsed = parsers.parse_bytes(content, file_type)
    return _chunk_parsed(parsed, chunk_size, chunk_overlap)


def _chunk_parsed(
    parsed: parsers.ParsedDocument,
    chunk_size: Optional[int],
    chunk_overlap: Optional[int],
) -> List[IngestedChunk]:
    settings = Settings.get_instance()
    size = chunk_size if chunk_size is not None else settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap

    chunks: List[IngestedChunk] = []
    index = 0
    for page in parsed.pages:
        cleaned = clean_text(page.text)
        if not cleaned.strip():
            continue
        for piece in chunk_text(cleaned, size, overlap):
            chunks.append(IngestedChunk(index=index, text=piece, page_number=page.page_number))
            index += 1

    if not chunks:
        raise parsers.ParsingError("Document produced no usable text chunks")

    return chunks
