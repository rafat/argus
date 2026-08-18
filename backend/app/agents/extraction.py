from google.adk.agents import LlmAgent

from app.models.claim import ClaimDraft


def build_extraction_agent() -> LlmAgent:
    return LlmAgent(
        name="extraction_agent",
        model="gemini-3.5-flash",
        description="Extracts explicit claims from one document section.",
        instruction=(
            "Extract only explicit, arguable claims from the document section. "
            "Do not decide whether claims are true and do not invent evidence. "
            "Return an empty list when there are no claims.\n\n"
            "Chapter: {chapter}\nSection: {section}\n"
            "Document text:\n{chunk_text}\n\n"
            "{correction}"
        ),
        output_schema=list[ClaimDraft],
        output_key="claim_drafts",
        include_contents="none",
    )
