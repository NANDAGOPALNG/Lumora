"""LLM provider abstraction.

Defines a minimal, provider-agnostic interface for text generation
(``BaseLLMProvider.generate``) so the RAG generation layer (see
``app.generation``) and ``ChatService`` never need to know which
concrete LLM backend is in use. Concrete providers (e.g.
``app.llm.gemini_provider.GeminiProvider``) implement this interface
and are responsible for translating their own SDK/HTTP exceptions into
the exception hierarchy defined here, so callers only ever need to
handle ``LLMProviderError`` and its subclasses - never a raw
provider/SDK exception.

Independent of FastAPI, SearchService, and any concrete provider SDK -
nothing here makes a network call.
"""

from abc import ABC, abstractmethod
from typing import Optional


class LLMProviderError(Exception):
    """Base class for all LLM provider failures.

    Callers (ChatService, the chat router) should catch this - or one
    of its subclasses below - rather than any provider-specific
    exception, so a provider can be swapped without changing error
    handling elsewhere.
    """


class LLMConfigurationError(LLMProviderError):
    """Raised when the provider is missing required configuration
    (e.g. an API key) or is given invalid input (e.g. an empty prompt).

    Distinct from a live provider/API failure - this is a setup
    problem, not a transient one.
    """


class LLMGenerationError(LLMProviderError):
    """Raised when a call to the underlying provider/API fails.

    Covers network errors, rate limiting, and other provider/API-side
    failures raised while generating a response.

    `status_code` carries the upstream provider's HTTP status code
    when the provider can determine one (e.g. 429 for rate limiting),
    so a caller (e.g. the chat router) can map this to an appropriate
    API-level status without needing to inspect any provider-specific
    exception. It's None when no such code is available.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class LLMResponseError(LLMProviderError):
    """Raised when the provider returns an empty, malformed, or
    otherwise unusable response, even though the call itself
    succeeded.
    """


class BaseLLMProvider(ABC):
    """Minimal, provider-agnostic text generation interface.

    A single async method: given a fully-constructed prompt, return
    the model's text response. No chat history, tool use, or streaming
    is part of this interface - those are separate concerns, out of
    scope for the current RAG chat flow.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate a text response for `prompt`.

        Args:
            prompt: the fully-constructed prompt to send to the model.

        Returns:
            The model's text response.

        Raises:
            LLMConfigurationError: if the provider isn't configured
                correctly, or `prompt` is invalid.
            LLMGenerationError: if the underlying provider/API call
                fails.
            LLMResponseError: if the provider returns an empty or
                unusable response.
        """
        raise NotImplementedError
