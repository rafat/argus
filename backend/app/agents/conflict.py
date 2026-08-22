from typing import Literal
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent


class ConflictResolution(BaseModel):
    is_conflict: bool = Field(
        description="True if Claim A and Claim B genuinely contradict or conflict semantically."
    )
    severity: Literal["low", "medium", "high"] = Field(
        description="Severity of the conflict."
    )
    explanation: str = Field(
        description="A detailed Socratic explanation of why these claims conflict, or empty if they do not."
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0."
    )


def build_conflict_agent() -> LlmAgent:
    return LlmAgent(
        name="conflict_agent",
        model="gemini-3.5-flash",
        description="Determines whether two claims genuinely contradict each other.",
        instruction=(
            "Compare the following two claims extracted from the same document:\n\n"
            "Claim A: {claim_a_text}\n"
            "Claim B: {claim_b_text}\n\n"
            "Analyze if they semantically contradict, oppose, or present incompatible arguments. "
            "Note that similarity is not contradiction. If they are just similar but do not contradict, "
            "set is_conflict=False.\n"
            "Explain your reasoning in the explanation field."
        ),
        output_schema=ConflictResolution,
        output_key="resolution",
        include_contents="none",
    )
