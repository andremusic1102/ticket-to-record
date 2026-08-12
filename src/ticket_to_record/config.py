"""Runtime configuration.

Everything is environment-driven and nothing is read from a hard-coded path, so
the same code runs on a laptop, in CI, and in a container without edits. The API
key has no default: a missing key must fail loudly at start-up rather than
halfway through a batch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["fake", "gemini"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: ProviderName = Field(default="fake", validation_alias="TTR_PROVIDER")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    # Pinned to a concrete version, never an alias like `gemini-flash-latest`.
    # This project exists to compare accuracy across runs; a model that changes
    # underneath the harness silently invalidates every number it has recorded.
    # Upgrading is a deliberate act with a re-run attached.
    gemini_model: str = Field(default="gemini-3.6-flash", validation_alias="TTR_GEMINI_MODEL")

    # Kept at 0 for extraction. Sampling buys nothing here and it makes the
    # evaluation harness non-reproducible, which is the one property it needs.
    temperature: float = Field(default=0.0, validation_alias="TTR_TEMPERATURE")


def load_settings() -> Settings:
    return Settings()
