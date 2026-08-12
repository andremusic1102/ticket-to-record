"""The provider interface.

The surface is one method wide on purpose. Everything this project does with a
model is "here is a schema, fill it in" — so that is the whole contract, and a
provider is a file rather than a subsystem.

Keeping it this narrow is what makes the evaluation harness possible: a
deterministic fake satisfying the same protocol means the pipeline, the CLI, and
every test can run end to end with no network, no key, and no spend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


class LLMError(RuntimeError):
    """A provider call failed, or returned something that is not the schema."""


@dataclass(frozen=True)
class LLMCall[T: BaseModel]:
    """A parsed response plus the accounting needed to evaluate it."""

    value: T
    raw_text: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class StructuredLLM(Protocol):
    """Anything that can fill in a Pydantic schema from a prompt."""

    @property
    def name(self) -> str:
        """Short provider identifier, recorded on every result."""
        ...

    @property
    def model(self) -> str:
        """Concrete model identifier, recorded on every result."""
        ...

    def structured[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMCall[T]:
        """Return an instance of ``schema``, or raise :class:`LLMError`."""
        ...
