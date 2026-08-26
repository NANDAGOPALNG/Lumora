"""Document ingestion core: parsing, cleaning, and chunking.

Produces in-memory chunk data (`extract_chunks`) from a stored document
file. Does not touch the database or persist anything itself - see a
later task for wiring this into DocumentService / the reindex endpoint.
"""

from app.ingestion.parsers import ParsingError
from app.ingestion.pipeline import IngestedChunk, extract_chunks

__all__ = ["extract_chunks", "IngestedChunk", "ParsingError"]
