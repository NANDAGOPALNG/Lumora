"""Shared validation helpers for retrieval primitives.

Both DenseRetriever and KeywordRetriever accept the same shape of
input (a query string, a workspace_id, an optional document_id, and a
top_k) and need to reject the same kinds of bad input the same way -
this module is the single place that logic lives, so the two
retrievers can't drift out of sync with each other.
"""

from typing import Union
from uuid import UUID

# Sensible default and hard ceiling for top_k, so a caller can't
# accidentally (or maliciously) request an unbounded number of results.
DEFAULT_TOP_K = 5
MAX_TOP_K = 50

UUIDLike = Union[UUID, str]


class RetrievalValidationError(Exception):
    """Raised when a retriever's search() is called with invalid input."""


def validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise RetrievalValidationError("query must be a non-empty string")
    return query


def validate_uuid(value: UUIDLike, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RetrievalValidationError(f"{field_name} must be a valid UUID") from exc


def validate_top_k(top_k: int) -> int:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise RetrievalValidationError("top_k must be a positive integer")
    return min(top_k, MAX_TOP_K)
