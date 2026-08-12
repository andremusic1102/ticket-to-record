"""Provider selection.

One place decides which provider is in use, so nothing downstream has to branch
on it. Adding a provider is a new module plus a line here.
"""

from __future__ import annotations

from ticket_to_record.config import Settings
from ticket_to_record.llm.base import LLMError, StructuredLLM
from ticket_to_record.llm.fake import FakeLLM


def build_llm(settings: Settings) -> StructuredLLM:
    if settings.provider == "fake":
        return FakeLLM()

    if settings.provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMError(
                "TTR_PROVIDER=gemini but GEMINI_API_KEY is unset. "
                "Export it, or put it in .env (which is gitignored)."
            )
        # Imported lazily so `--provider fake` never needs the vendor SDK loaded.
        from ticket_to_record.llm.gemini import GeminiLLM

        return GeminiLLM(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.temperature,
        )

    raise LLMError(f"Unknown provider: {settings.provider!r}")
