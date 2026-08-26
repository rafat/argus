from __future__ import annotations

import re

from app.guardrails.base import ContentGuardrail
from app.guardrails.result import GuardrailResult


# These are deliberately conservative deterministic checks for local testing.
# A managed provider can replace this implementation without changing callers.
PROMPT_INJECTION_PATTERNS = (
    r"\bignore\s+(?:all\s+)?previous\s+instructions\b",
    r"\bdisregard\s+(?:all\s+)?(?:previous|prior)\s+instructions\b",
    r"\byou\s+are\s+now\s+an?\s+(?:unrestricted|different|new)\b",
    r"\breveal\s+(?:the\s+)?(?:system|developer)\s+prompt\b",
    r"\b(?:hidden|secret|internal)\s+(?:system|developer)\s+prompt\b",
    r"\bdisable\s+(?:the\s+)?(?:integrity|safety|guardrail)\b",
    r"\b(?:system|developer)\s+message\s*:\s*ignore\b",
)

PII_PATTERNS = (
    ("email", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ("phone", r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)"),
    ("government_identifier", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("credit_card", r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
)


def _matches(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


class LocalContentGuardrail(ContentGuardrail):
    """Deterministic local guardrail used before a managed GCP provider exists."""

    async def inspect_input(self, text: str) -> GuardrailResult:
        if _matches(text, PROMPT_INJECTION_PATTERNS):
            return GuardrailResult.block(
                category="prompt_injection",
                reason="Instruction-override or guardrail-bypass language detected.",
                confidence=0.98,
            )
        return GuardrailResult.allow()

    async def inspect_document(self, text: str) -> GuardrailResult:
        if _matches(text, PROMPT_INJECTION_PATTERNS):
            return GuardrailResult.block(
                category="document_prompt_injection",
                reason="The document contains text attempting to control the analysis agent.",
                confidence=0.98,
            )
        for category, pattern in PII_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return GuardrailResult.review(
                    category=f"pii:{category}",
                    reason="Potential sensitive information detected in document content.",
                    confidence=0.85,
                )
        return GuardrailResult.allow()

    async def inspect_output(self, text: str) -> GuardrailResult:
        if _matches(text, PROMPT_INJECTION_PATTERNS):
            return GuardrailResult.block(
                category="unsafe_generated_content",
                reason="Generated output contains instruction-override or prompt-extraction language.",
                confidence=0.95,
            )
        if re.search(
            r"\b(?:write|draft|generate|compose|rewrite)\b.{0,80}\b(?:for you|for me|submission-ready)\b"
            r"|\bsubmission-ready\b.{0,80}\b(?:paragraph|section|essay|prose)\b.{0,80}\b(?:written|generated|drafted)\b",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            return GuardrailResult.block(
                category="ghostwriting_output",
                reason="Generated output appears to provide submission-ready writing.",
                confidence=0.9,
            )
        for category, pattern in PII_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return GuardrailResult.block(
                    category=f"output_pii:{category}",
                    reason="Generated output contains potential sensitive information.",
                    confidence=0.85,
                )
        return GuardrailResult.allow()
