from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent


class ArgumentAnalysis(BaseModel):
    logical_flaws: list[str] = Field(
        description="A list of structural logical weaknesses discovered in the reasoning (e.g. unstated premises, circular logic, false dichotomies, unearned leaps)."
    )
    coherence_score: float = Field(
        description="Coherence rating between 0.0 (incoherent) and 1.0 (highly consistent)."
    )


def build_argument_agent() -> LlmAgent:
    return LlmAgent(
        name="argument_agent",
        model="gemini-3.5-flash",
        description="Reviews logical premises, syllogisms, coherence, and exposes logical fallacies.",
        instruction=(
            "You are an expert logician and structural analyst. Your goal is to evaluate logical syllogisms, "
            "premises, and unstated assumptions behind the writer's reasoning.\n\n"
            "Analyze the argument context and the user's prompt:\n"
            "User's Question: {user_prompt}\n"
            "Argument Context:\n{context_text}\n\n"
            "Identify logical flaws, circular reasoning, unstated assumptions, or unearned leaps of logic. "
            "Provide a logical coherence rating."
        ),
        output_schema=ArgumentAnalysis,
        output_key="argument_res",
        include_contents="none",
    )
