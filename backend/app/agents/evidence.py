from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent


class EvidenceAnalysis(BaseModel):
    findings: str = Field(
        description="A critical review of the evidentiary strength of the argument, highlighting any logical leaps or missing citations."
    )
    suggestions: list[str] = Field(
        description="Specific types of empirical data, historical precedents, or structural verification the user needs to supply."
    )


def build_evidence_agent() -> LlmAgent:
    return LlmAgent(
        name="evidence_agent",
        model="gemini-3.5-flash",
        description="Evaluates evidentiary coverage, citation completeness, and logical gaps between claims and cited evidence.",
        instruction=(
            "You are an expert empirical analyst. Your goal is to review the argument context and evaluate "
            "evidentiary coverage, citation completeness, and the logical gap between the claim and the cited sources.\n\n"
            "Critical Boundary: Absence of a citation does not establish that a claim is false. "
            "You must explicitly distinguish between:\n"
            "1. Unsupported within the supplied context (missing citations but not necessarily wrong),\n"
            "2. Weakly supported,\n"
            "3. Requiring external verification, and\n"
            "4. Contradicted by supplied evidence.\n"
            "Do not infer factual falsity merely from missing citations.\n\n"
            "Analyze the argument context and the user's prompt:\n"
            "User's Question: {user_prompt}\n"
            "Argument Context:\n{context_text}\n\n"
            "Provide a highly objective analysis of the empirical coverage and citation completeness. Highlight where the writer asserts a fact "
            "as absolute truth without referencing external evidence or verifiable data, or where there are logical gaps between "
            "the claim and the cited evidence. Suggest what kind of structural evidence, empirical data, or source structure would back these assertions."
        ),
        output_schema=EvidenceAnalysis,
        output_key="evidence_res",
        include_contents="none",
    )
