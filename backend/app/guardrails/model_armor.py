from __future__ import annotations

import asyncio
import os
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from app.guardrails.base import ContentGuardrail
from app.guardrails.result import GuardrailResult


class ModelArmorContentGuardrail(ContentGuardrail):
    """Model Armor REST adapter kept behind Argus's guardrail interface."""

    def __init__(self) -> None:
        self.project = os.environ["MODEL_ARMOR_PROJECT"]
        self.location = os.environ["MODEL_ARMOR_LOCATION"]
        self.template_id = os.environ["MODEL_ARMOR_TEMPLATE_ID"]
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self._session = AuthorizedSession(credentials)
        self._template = (
            f"projects/{self.project}/locations/{self.location}/templates/"
            f"{self.template_id}"
        )
        self._endpoint = f"https://modelarmor.{self.location}.rep.googleapis.com/v1/{self._template}"

    async def inspect_input(self, text: str) -> GuardrailResult:
        return await asyncio.to_thread(self._sanitize, "sanitizeUserPrompt", {"userPromptData": {"text": text}})

    async def inspect_document(self, text: str) -> GuardrailResult:
        return await asyncio.to_thread(self._sanitize, "sanitizeUserPrompt", {"userPromptData": {"text": text}})

    async def inspect_output(self, text: str) -> GuardrailResult:
        return await asyncio.to_thread(self._sanitize, "sanitizeModelResponse", {"modelResponseData": {"text": text}})

    def _sanitize(self, operation: str, payload: dict[str, Any]) -> GuardrailResult:
        response = self._session.post(f"{self._endpoint}:{operation}", json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        result = body.get("sanitizationResult", {})
        match_state = result.get("filterMatchState", result.get("filter_match_state", ""))
        invocation = result.get("invocationResult", result.get("invocation_result", "SUCCESS"))
        if str(invocation).upper() not in {"SUCCESS", "INVOCATION_RESULT_UNSPECIFIED"}:
            return GuardrailResult.review(category="model_armor_invocation", reason="Model Armor could not complete sanitization.")
        if str(match_state).upper() == "MATCH_FOUND":
            return GuardrailResult.block(category="model_armor_match", reason="Model Armor detected content violating the configured safety policy.")
        sanitized_text = result.get("deidentifyResult", {}).get("data", {}).get("text")
        return GuardrailResult.allow(sanitized_text=sanitized_text)
