"""Gemini provider: BaseLLMProvider backed by the Gemini API.

Uses Google's official ``google-genai`` SDK (the actively maintained
successor to ``google-generativeai``). Configuration (API key, model
name) comes from ``Settings`` - nothing here is hard-coded - and the
underlying SDK client is created lazily on first use and cached for
the lifetime of the provider instance, mirroring the lazy-singleton
pattern already used by the embedding engine and reranker
(``app/embeddings/engine.py``, ``app/retrieval/reranker.py``).

All google-genai SDK/HTTP exceptions are translated into the
provider-agnostic exceptions defined in ``app.llm.base`` - callers
never see a raw ``google.genai`` exception, an API key, or any other
provider-internal detail.
"""

from typing import Optional

from google import genai
from google.genai import errors as genai_errors

from app.config.settings import Settings
from app.llm.base import (
    BaseLLMProvider,
    LLMConfigurationError,
    LLMGenerationError,
    LLMResponseError,
)


class GeminiProvider(BaseLLMProvider):
    """Generates text via the Gemini API.

    `api_key` / `model_name` default to `Settings.gemini_api_key` /
    `Settings.gemini_model_name` when not given explicitly, so the
    provider can be constructed with `GeminiProvider()` in normal use
    but still overridden (e.g. in tests) without touching Settings.

    The `genai.Client` is created lazily, on first `generate()` call,
    and reused across subsequent calls on the same instance - it is
    not recreated per request.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        settings = Settings.get_instance()
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model_name = model_name if model_name is not None else settings.gemini_model_name
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured")

        try:
            self._client = genai.Client(api_key=self._api_key)
        except Exception as exc:
            raise LLMConfigurationError("Failed to initialize the Gemini client") from exc

        return self._client

    async def generate(self, prompt: str) -> str:
        """Generate a text response for `prompt` using Gemini.

        Raises:
            LLMConfigurationError: if GEMINI_API_KEY isn't configured,
                the client fails to initialize, or `prompt` is invalid.
            LLMGenerationError: if the Gemini API call itself fails
                (network error, rate limiting, server error, etc.).
            LLMResponseError: if Gemini returns an empty or unusable
                response.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMConfigurationError("prompt must be a non-empty string")

        client = self._get_client()

        try:
            response = await client.aio.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
        except genai_errors.APIError as exc:
            raise LLMGenerationError(
                "Gemini API request failed", status_code=exc.code
            ) from exc
        except Exception as exc:
            raise LLMGenerationError("Gemini API request failed") from exc

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise LLMResponseError("Gemini returned an empty response")

        return text
