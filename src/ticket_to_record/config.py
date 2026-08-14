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

    # Kept at 0 for extraction: sampling buys nothing when the task is copying
    # values out of a document.
    #
    # It was also claimed here that this made the harness reproducible. **That
    # was wrong and it was measured wrong.** Six identical runs over the same 50
    # tickets put `under_coverage` between 69.4% and 77.6% and `product_model`
    # between 85.1% and 89.4%, while `serial_number` and `purchase_date` did not
    # move at all. Temperature 0 constrains sampling; it does not make a hosted
    # model deterministic, and the fields that drift are the ones that need a
    # judgement rather than a copy.
    #
    # The harness answer is `ttr evaluate --repeat N`, which reports each
    # field's mean and range. Anything narrower than that range is not a result.
    temperature: float = Field(default=0.0, validation_alias="TTR_TEMPERATURE")


def load_settings() -> Settings:
    return Settings()
