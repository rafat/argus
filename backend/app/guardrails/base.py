from abc import ABC, abstractmethod

from app.guardrails.result import GuardrailResult


class ContentGuardrail(ABC):
    """Stable application interface for local or managed guardrail providers."""

    @abstractmethod
    async def inspect_input(self, text: str) -> GuardrailResult:
        """Inspect a user prompt before it reaches an agent workflow."""

    @abstractmethod
    async def inspect_document(self, text: str) -> GuardrailResult:
        """Inspect extracted document text, which is always untrusted data."""

    @abstractmethod
    async def inspect_output(self, text: str) -> GuardrailResult:
        """Inspect generated text before it is persisted or returned."""
