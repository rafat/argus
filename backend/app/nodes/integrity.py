import re
from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from app.models.interception import InterceptionRecord
from app.tools.firestore import FirestoreRepository

# 1. Deterministic Regex Pre-Filters
GHOSTWRITING_REGEXES = [
    r"\b(write|draft|generate|compose|create|make|code|rewrite)\b.*\b(section|paragraph|chapter|for me|page|code|function|class|essay|prose|draft)\b",
    r"\b(write|draft|generate)\s+a\s+(paragraph|section|intro|conclusion|outline|thesis|paper)\b",
    r"\bwrite\s+this\s+for\s+me\b",
    r"\bcan\s+you\s+write\b",
    r"\bgive\s+me\s+the\s+text\b",
    r"\brewrite\s+this\s+for\s+me\b",
]


class IntentClassification(BaseModel):
    is_ghostwriting: bool = Field(
        description="True if the prompt asks the AI to draft paragraphs, write sections, generate code, or compose prose directly on behalf of the user."
    )
    reason: str = Field(
        description="Brief explanation of why this was or was not classified as ghostwriting."
    )


def build_integrity_classifier() -> LlmAgent:
    return LlmAgent(
        name="integrity_classifier",
        model="gemini-3.5-flash",
        description="Classifies whether a user prompt asks for direct text generation or socratic coaching.",
        instruction=(
            "You are a strict academic policy auditor. Your job is to classify if the user prompt is asking "
            "for direct ghostwriting (i.e. generating prose, writing sections, rewriting text, drafting paragraphs, "
            "or generating source code on their behalf) OR if they are asking for analytical socratic coaching "
            "(e.g., asking for advice, outlines, weaknesses, reviews, or questions to help them write it themselves).\n\n"
            "User Prompt: {user_prompt}\n\n"
            "If they ask to write, draft, generate, or compose any text/code on their behalf, set is_ghostwriting=True. "
            "If they ask for feedback, review, logic checks, or guidance, set is_ghostwriting=False."
        ),
        output_schema=IntentClassification,
        output_key="classification",
        include_contents="none",
    )


class IntegrityInterceptor:
    """
    Enforces the 'reasoning partner rather than ghostwriter' boundary.
    Performs fast rule checks, semantic classification, and logs audit entries in Firestore.
    """

    def __init__(self, repository: FirestoreRepository = None):
        self.repository = repository or FirestoreRepository()
        self.classifier = build_integrity_classifier()

    async def analyze(self, user_prompt: str, document_id: str) -> InterceptionRecord | None:
        # Step 1: Pre-filter with deterministic regexes
        prompt_lower = user_prompt.lower()
        for pattern in GHOSTWRITING_REGEXES:
            if re.search(pattern, prompt_lower):
                record = InterceptionRecord(
                    id=str(uuid4()),
                    document_id=document_id,
                    user_prompt=user_prompt,
                    classification_reason="Regex Match: Direct drafting/writing pattern detected.",
                    timestamp=datetime.utcnow()
                )
                self.repository.save_interception(document_id, record)
                return record

        # Step 2: Semantic check via fast LLM classification
        # Since the LlmAgent expects run context or we can mock/run it, we can call it.
        # Wait, since ADK LlmAgent has runner integration, we can also use a simple direct call to Gemini to keep it extremely fast!
        # Let's run the LlmAgent classifier using the ADK Runner or via standard GenAI SDK to be robust.
        # To run the LlmAgent in ADK 2.x dynamically:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        
        sessions = InMemorySessionService()
        session_id = str(uuid4())
        await sessions.create_session(
            app_name="argus",
            user_id="system",
            session_id=session_id,
        )
        
        runner = Runner(
            app_name="argus",
            node=self.classifier,
            session_service=sessions
        )
        
        classification_result = None
        from google.genai import types
        
        async for event in runner.run_async(
            user_id="system",
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text="Classify prompt")]
            ),
            state_delta={"user_prompt": user_prompt},
            invocation_id=session_id
        ):
            if event.node_info.name == "integrity_classifier" and event.output is not None:
                classification_result = event.output

        if classification_result and classification_result.get("classification"):
            outcome: IntentClassification = classification_result["classification"]
            if outcome.is_ghostwriting:
                record = InterceptionRecord(
                    id=str(uuid4()),
                    document_id=document_id,
                    user_prompt=user_prompt,
                    classification_reason=outcome.reason or "LLM Classification: Ghostwriting intent detected.",
                    timestamp=datetime.utcnow()
                )
                self.repository.save_interception(document_id, record)
                return record

        return None
