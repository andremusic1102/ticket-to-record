"""Gemini provider.

Structured output is requested at the API level (``response_schema``) rather
than by asking the model in prose to "reply with JSON". The difference matters:
schema enforcement happens during decoding, so malformed JSON is not a failure
mode we have to retry around, and the schema stays in one place — the Pydantic
model — instead of being duplicated into the prompt where it can drift.

The parsed result is still validated on our side. A response can satisfy the
JSON Schema and still be wrong for us, and a provider that silently changes how
it handles a keyword should surface as a loud error rather than as a quiet
accuracy regression.
"""

from __future__ import annotations

import time

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from ticket_to_record.llm.base import LLMCall, LLMError


class GeminiLLM:
    """Satisfies :class:`~ticket_to_record.llm.base.StructuredLLM`."""

    def __init__(self, *, api_key: str, model: str, temperature: float = 0.0) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    def structured[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMCall[T]:
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=self._temperature,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except Exception as exc:  # provider SDKs raise a wide variety of types
            raise LLMError(f"{self._model} call failed: {exc}") from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        raw_text = response.text or ""
        parsed = response.parsed
        if isinstance(parsed, schema):
            value = parsed
        else:
            try:
                value = schema.model_validate_json(raw_text)
            except ValidationError as exc:
                raise LLMError(
                    f"{self._model} returned a payload that is not {schema.__name__}: {exc}"
                ) from exc

        usage = response.usage_metadata
        return LLMCall(
            value=value,
            raw_text=raw_text,
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
