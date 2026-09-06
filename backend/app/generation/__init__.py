"""RAG generation-layer primitives for Lumora.

Exposes the prompt-construction component (`RagPromptBuilder`) used to
turn a query plus a retrieved `BuiltContext` into a grounded prompt for
a `BaseLLMProvider`. Actual LLM invocation lives in `app.llm`; this
package only builds the prompt text.
"""

from app.generation.prompt_builder import RagPromptBuilder

__all__ = ["RagPromptBuilder"]
