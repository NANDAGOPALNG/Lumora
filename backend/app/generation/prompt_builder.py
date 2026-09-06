"""RAG prompt construction.

Implements only the prompt-construction step of the chat flow

    ChatService -> SearchService -> ContextBuilder -> RAG prompt -> BaseLLMProvider

Turns a user query plus an already-built retrieval context
(``app.retrieval.context_builder.BuiltContext``) into a single
grounded prompt string ready to hand to a `BaseLLMProvider`. This is a
pure, deterministic string transformation - no LLM call, network
access, database, or vector store is touched here, and no chat
history is included (that's a later persistence concern, out of scope
for this task).
"""

from app.retrieval.context_builder import BuiltContext

_SYSTEM_INSTRUCTIONS = """\
You are an assistant that answers questions using only the retrieved \
context provided below. Follow these rules:

1. Base your answer primarily on the information in the context.
2. Do not invent facts that are not supported by the context.
3. If the context does not contain enough information to answer the \
question, say clearly that the available knowledge does not provide \
enough information, rather than guessing.
4. When you use information from a numbered source (e.g. "[1]"), \
refer to it using that same number so the answer stays traceable back \
to its source.
5. Give a direct, useful answer to the question - do not simply repeat \
or dump the context back at the user."""


class RagPromptBuilder:
    """Builds a grounded RAG prompt from a query and retrieval context.

    Stateless - safe to construct once and reuse across many
    build_prompt() calls, or to construct fresh per call.
    """

    def build_prompt(self, query: str, context: BuiltContext) -> str:
        """Combine `query` and `context` into a single prompt string.

        `context.text` is inserted verbatim (it already contains the
        numbered "[n] filename (chunk i, source: X)" citation headers
        produced by ContextBuilder) - no reformatting or truncation is
        applied here. When `context.text` is empty (no retrieved
        content), the prompt still instructs the model to say the
        available knowledge does not provide enough information,
        rather than omitting the context section entirely.
        """
        context_text = context.text if context.text.strip() else (
            "(No relevant context was found for this query.)"
        )

        return (
            f"{_SYSTEM_INSTRUCTIONS}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}\n\n"
            "Answer:"
        )
