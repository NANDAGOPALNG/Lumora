"""Query Rewriter: deterministic query normalization (no LLM).

Implements only the deterministic-normalization half of the "Query
Rewriter" stage of the larger LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

and the "Cleaning and normalizing the input" part of the HLD's Step 3
(Query Preprocessing). Ambiguous-query rewriting and embedding
generation are separate concerns: this module never calls an LLM,
never generates an embedding, and never touches the network, a
database, or a vector store - it's a pure string transformation. A
future LLM-based rewriting strategy can be layered on top of (or
substituted for) this one without changing its interface, but that
strategy is out of scope here.
"""

from dataclasses import dataclass

from app.retrieval.validation import validate_query


@dataclass
class RewrittenQuery:
    """The result of deterministic query normalization.

    `original` is the raw input exactly as given (after validation);
    `normalized` is the retrieval-ready query - whitespace-trimmed,
    with internal runs of whitespace collapsed to single spaces.
    Wording and semantic content are otherwise left untouched: no
    synonym replacement, spelling correction, stemming, or semantic
    rewriting is performed.
    """

    original: str
    normalized: str


class QueryRewriter:
    """Deterministic query preprocessor.

    Stateless - safe to construct once and reuse across many rewrite()
    calls, or to construct fresh per call. Produces identical output
    for identical input every time.
    """

    def rewrite(self, query: str) -> RewrittenQuery:
        """Validate and normalize `query`, returning both the original
        and normalized forms.

        Raises RetrievalValidationError (via the shared validation
        helper) if `query` is not a non-empty, non-whitespace-only
        string - the same rule every other retrieval primitive already
        enforces.
        """
        validated_query = validate_query(query)
        normalized = " ".join(validated_query.split())

        return RewrittenQuery(original=validated_query, normalized=normalized)
