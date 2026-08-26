import logging
from uuid import uuid4
from pydantic import BaseModel, Field, ValidationError
from google.adk.workflow import FunctionNode, START, Workflow
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.socratic import build_socratic_agent, SocraticQuestions
from app.agents.evidence import build_evidence_agent, EvidenceAnalysis
from app.agents.argument import build_argument_agent, ArgumentAnalysis
from app.agents.coaching import build_coaching_coordinator_agent, CoachingSynthesis

logger = logging.getLogger(__name__)


class CoachingResult(BaseModel):
    coaching_feedback: str = Field(
        description="Synthesized coaching feedback compiled by the coordinator."
    )
    socratic_questions: list[str] = Field(
        description="Targeted questions from the Socratic Specialist."
    )
    evidence_findings: str = Field(
        description="Empirical citation review findings from the Evidence Specialist."
    )
    evidence_suggestions: list[str] = Field(
        description="Source validation suggestions from the Evidence Specialist."
    )
    logical_flaws: list[str] = Field(
        description="Logical fallacies caught by the Argument Specialist."
    )
    coherence_score: float = Field(
        description="Logical consistency rating from the Argument Specialist."
    )


def _prepare_synthesis_inputs(ctx, node_input):
    """
    Format outputs from the specialist agents in ctx.state 
    so that they can be formatted inside the synthesis prompt.
    Safely rehydrates dictionaries crossing the ADK boundary.
    """
    socratic_raw = ctx.state.get("socratic_res")
    evidence_raw = ctx.state.get("evidence_res")
    argument_raw = ctx.state.get("argument_res")

    # Rehydrate Socratic questions
    try:
        socratic_res = SocraticQuestions.model_validate(socratic_raw) if socratic_raw else None
    except ValidationError:
        socratic_res = None

    if socratic_res:
        socratic_out = "\n".join(f"- {q}" for q in socratic_res.questions)
    else:
        socratic_out = "No targeted questions suggested."

    # Rehydrate Evidence analysis
    try:
        evidence_res = EvidenceAnalysis.model_validate(evidence_raw) if evidence_raw else None
    except ValidationError:
        evidence_res = None

    if evidence_res:
        suggs = "\n".join(f"- {s}" for s in evidence_res.suggestions)
        evidence_out = f"Findings:\n{evidence_res.findings}\nSuggestions:\n{suggs}"
    else:
        evidence_out = "No empirical citation issues flagged."

    # Rehydrate Argument logic flaws
    try:
        argument_res = ArgumentAnalysis.model_validate(argument_raw) if argument_raw else None
    except ValidationError:
        argument_res = None

    if argument_res:
        flaws = "\n".join(f"- {f}" for f in argument_res.logical_flaws)
        argument_out = f"Coherence Score: {argument_res.coherence_score}\nLogical flaws:\n{flaws}"
    else:
        argument_out = "No structural fallacies detected."

    ctx.state["socratic_output"] = socratic_out
    ctx.state["evidence_output"] = evidence_out
    ctx.state["argument_output"] = argument_out

    return {}


def build_coaching_workflow() -> Workflow:
    """
    Build the ADK Socratic Coaching Workflow.
    Executes a parallel fan-out over specialized agents:
      START -> [Socratic, Evidence, Argument] -> Prepare Node -> Coordinator Synthesis Node
    """
    socratic_node = build_socratic_agent()
    evidence_node = build_evidence_agent()
    argument_node = build_argument_agent()

    prepare_node = FunctionNode(
        func=_prepare_synthesis_inputs,
        name="prepare_synthesis",
    )
    # The preceding fan-out produces three different typed agent outputs.
    # Leave this join node schema-less: it reads those outputs from ctx.state,
    # normalizes them into state, and hands state to the coordinator. Declaring
    # dict here makes ADK 2.5 reject the graph because each fan-out edge has a
    # different output schema.

    coordinator_node = build_coaching_coordinator_agent()

    return Workflow(
        name="collaborative_coaching_workflow",
        edges=[
            (
                START,
                (socratic_node, evidence_node, argument_node),
                prepare_node,
                coordinator_node,
            )
        ],
    )


async def run_coaching_workflow(
    user_prompt: str,
    context_text: str,
) -> CoachingResult:
    """
    Runs the compiled ADK collaborative coaching workflow using ADK Runner.
    Gathers intermediate specialist outputs and compiles a structured CoachingResult.
    Safely rehydrates dictionaries crossing the ADK runner event output boundary.
    """
    workflow = build_coaching_workflow()
    sessions = InMemorySessionService()
    session_id = str(uuid4())

    await sessions.create_session(
        app_name="argus",
        user_id="user",
        session_id=session_id,
    )

    runner = Runner(
        app_name="argus",
        node=workflow,
        session_service=sessions,
    )

    final_feedback = ""
    socratic_questions = []
    evidence_findings = "No empirical citation issues flagged."
    evidence_suggestions = []
    logical_flaws = []
    coherence_score = 1.0

    async for event in runner.run_async(
        user_id="user",
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text="Synthesize coaching")],
        ),
        invocation_id=session_id,
        state_delta={
            "user_prompt": user_prompt,
            "context_text": context_text,
        },
    ):
        if event.node_info.name == "socratic_agent" and event.output is not None:
            res = event.output.get("socratic_res")
            if res:
                try:
                    parsed = SocraticQuestions.model_validate(res)
                    socratic_questions = parsed.questions
                except ValidationError:
                    pass
        elif event.node_info.name == "evidence_agent" and event.output is not None:
            res = event.output.get("evidence_res")
            if res:
                try:
                    parsed = EvidenceAnalysis.model_validate(res)
                    evidence_findings = parsed.findings
                    evidence_suggestions = parsed.suggestions
                except ValidationError:
                    pass
        elif event.node_info.name == "argument_agent" and event.output is not None:
            res = event.output.get("argument_res")
            if res:
                try:
                    parsed = ArgumentAnalysis.model_validate(res)
                    logical_flaws = parsed.logical_flaws
                    coherence_score = parsed.coherence_score
                except ValidationError:
                    pass
        elif event.node_info.name == "coaching_coordinator_agent" and event.output is not None:
            res = event.output.get("synthesized_feedback")
            if res:
                try:
                    parsed = CoachingSynthesis.model_validate(res)
                    final_feedback = parsed.coaching_feedback
                except ValidationError:
                    pass

    # ADK stores output_key values in session state. Depending on the runner
    # event path, the final coordinator event may not carry the output payload
    # itself, so use the persisted state as the authoritative fallback.
    session = await sessions.get_session(
        app_name="argus",
        user_id="user",
        session_id=session_id,
    )
    if session:
        state = session.state
        if not final_feedback:
            raw_feedback = state.get("synthesized_feedback")
            try:
                final_feedback = CoachingSynthesis.model_validate(raw_feedback).coaching_feedback
            except (ValidationError, TypeError):
                pass
        if not socratic_questions:
            try:
                socratic_questions = SocraticQuestions.model_validate(state.get("socratic_res")).questions
            except (ValidationError, TypeError):
                pass
        if not evidence_suggestions or evidence_findings == "No empirical citation issues flagged.":
            try:
                evidence = EvidenceAnalysis.model_validate(state.get("evidence_res"))
                evidence_findings = evidence.findings
                evidence_suggestions = evidence.suggestions
            except (ValidationError, TypeError):
                pass
        if not logical_flaws:
            try:
                argument = ArgumentAnalysis.model_validate(state.get("argument_res"))
                logical_flaws = argument.logical_flaws
                coherence_score = argument.coherence_score
            except (ValidationError, TypeError):
                pass

    if not final_feedback:
        raise RuntimeError("ADK Socratic coaching workflow failed to synthesize a response.")

    return CoachingResult(
        coaching_feedback=final_feedback,
        socratic_questions=socratic_questions,
        evidence_findings=evidence_findings,
        evidence_suggestions=evidence_suggestions,
        logical_flaws=logical_flaws,
        coherence_score=coherence_score,
    )
