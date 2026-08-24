from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent


class SocraticQuestions(BaseModel):
    questions: list[str] = Field(
        description="Exactly 2 to 3 targeted Socratic questions prompting critical reflection on logic, assumptions, evidence, scope, or consistency."
    )


def build_socratic_agent() -> LlmAgent:
    return LlmAgent(
        name="socratic_agent",
        model="gemini-3.5-flash",
        description="Generates targeted Socratic questions based on claims, conflicts, and user prompt context.",
        instruction=(
            "You are a Socratic reasoning coach. Your goal is to guide the writer to strengthen their argument "
            "WITHOUT giving them direct answers or writing any prose on their behalf.\n\n"
            "Analyze the argument context and the user's prompt:\n"
            "User's Question: {user_prompt}\n"
            "Argument Context (Claims / Conflicts / Citations):\n{context_text}\n\n"
            "Formulate exactly 2 to 3 deep, critical Socratic questions. "
            "Make them highly targeted to structural weaknesses, unstated assumptions, consistency, scope, "
            "or evidentiary gaps in their logic."
        ),
        output_schema=SocraticQuestions,
        output_key="socratic_res",
        include_contents="none",
    )
