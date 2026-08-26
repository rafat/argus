from typing import Literal

from pydantic import BaseModel, Field


GuardrailAction = Literal["allow", "block", "review"]


class GuardrailResult(BaseModel):
    """Provider-neutral result for an input, document, or model-output check."""

    allowed: bool
    action: GuardrailAction
    category: str | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sanitized_text: str | None = None

    @classmethod
    def allow(cls, *, sanitized_text: str | None = None) -> "GuardrailResult":
        return cls(allowed=True, action="allow", sanitized_text=sanitized_text)

    @classmethod
    def review(
        cls,
        *,
        category: str,
        reason: str,
        confidence: float | None = None,
        sanitized_text: str | None = None,
    ) -> "GuardrailResult":
        return cls(
            allowed=True,
            action="review",
            category=category,
            reason=reason,
            confidence=confidence,
            sanitized_text=sanitized_text,
        )

    @classmethod
    def block(
        cls,
        *,
        category: str,
        reason: str,
        confidence: float | None = None,
    ) -> "GuardrailResult":
        return cls(
            allowed=False,
            action="block",
            category=category,
            reason=reason,
            confidence=confidence,
        )
