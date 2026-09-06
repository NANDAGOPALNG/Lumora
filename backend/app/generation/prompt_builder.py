"""RAG prompt construction.

Implements only the prompt-construction step of the chat flow

    ChatService -> SearchService -> ContextBuilder -> RAG prompt -> BaseLLMProvider

Turns a user query plus an already-built retrieval context
(``app.retrieval.context_builder.BuiltContext``) into a single
grounded prompt string ready to hand to a `BaseLLMProvider`. This is a
pure, deterministic string transformation - no LLM call, network
access, database, or vector store is touched here.

Optionally also takes prior conversation turns (``ConversationTurn``)
so a follow-up question can be understood in context. History is
deliberately a plain (role, content) pair, not a database model - this
module stays independent of ``app.models`` / SQLAlchemy; ChatService
is responsible for turning persisted ``Message`` rows into
``ConversationTurn``s before calling ``build_prompt``. History is
included only as conversational context (e.g. to resolve "it"/"that"
in a follow-up) - it is never treated as a source of facts, and the
grounded-RAG instructions below are unchanged and unweakened by its
presence.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

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

_HISTORY_INSTRUCTION = """\
6. Prior conversation is included below for conversational context \
only - e.g. to understand what a follow-up question like "it" or \
"that" refers to. It is not a source of facts: never treat something \
said earlier in the conversation as established truth, and continue \
to base every factual claim only on the Context section, following \
rules 1-5 above."""


@dataclass
class ConversationTurn:
    """One prior message in a conversation: `role` is "user" or
    "assistant"; `content` is that message's text.
    """

    role: str
    content: str


class RagPromptBuilder:
    """Builds a grounded RAG prompt from a query, retrieval context,
    and optional conversation history.

    Stateless - safe to construct once and reuse across many
    build_prompt() calls, or to construct fresh per call.
    """

    def build_prompt(
        self,
        query: str,
        context: BuiltContext,
        history: Optional[Sequence[ConversationTurn]] = None,
    ) -> str:
        """Combine `query`, `context`, and optional `history` into a
        single prompt string.

        `context.text` is inserted verbatim (it already contains the
        numbered "[n] filename (chunk i, source: X)" citation headers
        produced by ContextBuilder) - no reformatting or truncation is
        applied here. When `context.text` is empty (no retrieved
        content), the prompt still instructs the model to say the
        available knowledge does not provide enough information,
        rather than omitting the context section entirely.

        When `history` is given and non-empty, rule 6 (above) is
        appended to the system instructions and a "Prior conversation"
        section is inserted before the Context section - the Context
        and Question sections themselves are unchanged and remain
        clearly, separately labeled either way, so the current RAG
        context and current question are never conflated with
        conversation history.
        """
        context_text = context.text if context.text.strip() else (
            "(No relevant context was found for this query.)"
        )

        history = history or []
        if history:
            instructions = f"{_SYSTEM_INSTRUCTIONS}\n{_HISTORY_INSTRUCTION}"
            history_text = "\n".join(
                f"{turn.role.capitalize()}: {turn.content}" for turn in history
            )
            history_section = (
                f"Prior conversation (context only, not a source of facts):\n"
                f"{history_text}\n\n"
            )
        else:
            instructions = _SYSTEM_INSTRUCTIONS
            history_section = ""

        return (
            f"{instructions}\n\n"
            f"{history_section}"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}\n\n"
            "Answer:"
        )
