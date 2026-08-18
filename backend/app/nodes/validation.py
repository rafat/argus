from google.adk.agents.context import Context

from app.models.claim import ClaimDraft


def validate_claims(ctx: Context, node_input: list[ClaimDraft]) -> list[ClaimDraft]:
    # The ADK node input schema performs the first validation before this runs.
    # This node owns the workflow route and correction state.
    ctx.state["correction"] = ""
    ctx.route = "valid"
    return node_input


def request_correction(ctx: Context, node_input=None) -> dict:
    ctx.state["correction"] = (
        "Previous extraction output was invalid. Return only a JSON array of "
        "objects matching the ClaimDraft schema."
    )
    return {}
