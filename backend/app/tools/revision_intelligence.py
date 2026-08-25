import difflib
import logging
from uuid import uuid4
from pydantic import BaseModel, Field
from google.genai import types

from app.models.claim import Claim
from app.models.issue import Issue, IssueEvent
from app.tools.firestore import FirestoreRepository
from app.tools.vector_search import EmbeddingService, cosine_similarity

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# Paragraph splitting helper
# -------------------------------------------------------------
def split_paragraphs(text: str) -> list[str]:
    """Splits a document text into list of clean paragraphs."""
    if not text:
        return []
    raw_blocks = text.split("\n\n")
    paragraphs = []
    for block in raw_blocks:
        cleaned = " ".join(block.split()).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


# -------------------------------------------------------------
# Paragraph difference block aligner
# -------------------------------------------------------------
class RevisionChange(BaseModel):
    location: str
    change_type: str  # e.g., "added", "removed", "modified", "unchanged"
    before: str | None = None
    after: str | None = None
    similarity: float = 0.0


def diff_paragraphs(v1_text: str, v2_text: str) -> list[str]:
    """
    Computes paragraph-level differences using SequenceMatcher to align paragraphs.
    """
    v1_paras = split_paragraphs(v1_text)
    v2_paras = split_paragraphs(v2_text)

    changes = []
    sm = difflib.SequenceMatcher(None, v1_paras, v2_paras)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for idx, p in enumerate(v1_paras[i1:i2]):
                changes.append(
                    RevisionChange(
                        location=f"Paragraph {i1 + idx + 1}",
                        change_type="unchanged",
                        before=p,
                        after=p,
                        similarity=1.0,
                    )
                )
        elif tag == "insert":
            for idx, p in enumerate(v2_paras[j1:j2]):
                changes.append(
                    RevisionChange(
                        location=f"Paragraph {j1 + idx + 1}",
                        change_type="added",
                        before=None,
                        after=p,
                        similarity=0.0,
                    )
                )
        elif tag == "delete":
            for idx, p in enumerate(v1_paras[i1:i2]):
                changes.append(
                    RevisionChange(
                        location=f"Paragraph {i1 + idx + 1}",
                        change_type="removed",
                        before=p,
                        after=None,
                        similarity=0.0,
                    )
                )
        elif tag == "replace":
            len_before = i2 - i1
            len_after = j2 - j1
            max_len = max(len_before, len_after)
            for offset in range(max_len):
                before_p = v1_paras[i1 + offset] if offset < len_before else None
                after_p = v2_paras[j1 + offset] if offset < len_after else None

                if before_p and after_p:
                    ratio = difflib.SequenceMatcher(None, before_p, after_p).ratio()
                    changes.append(
                        RevisionChange(
                            location=f"Paragraph {i1 + offset + 1}",
                            change_type="modified",
                            before=before_p,
                            after=after_p,
                            similarity=ratio,
                        )
                    )
                elif before_p:
                    changes.append(
                        RevisionChange(
                            location=f"Paragraph {i1 + offset + 1}",
                            change_type="removed",
                            before=before_p,
                            after=None,
                            similarity=0.0,
                        )
                    )
                elif after_p:
                    changes.append(
                        RevisionChange(
                            location=f"Paragraph {j1 + offset + 1}",
                            change_type="added",
                            before=None,
                            after=after_p,
                            similarity=0.0,
                        )
                    )
    return changes


# -------------------------------------------------------------
# Semantic Claim Matching (Greedy bipartite one-to-one mapping constraint)
# -------------------------------------------------------------
def match_v1_to_v2_claims(
    v1_claims: list[Claim],
    v2_claims: list[Claim],
    embedding_service: EmbeddingService = None,
    min_similarity: float = 0.65,
) -> dict[str, str]:
    """
    Match V1 claims to V2 claims based on semantic vector similarity with a strict
    greedy bipartite one-to-one constraint.
    Returns a dictionary mapping: v1_claim_id -> v2_claim_id
    """
    # Force generate missing embeddings
    for c in v1_claims:
        if not c.embedding and embedding_service:
            try:
                c.embedding = embedding_service.embed(c.text)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for claim {c.id}: {e}")

    for c in v2_claims:
        if not c.embedding and embedding_service:
            try:
                c.embedding = embedding_service.embed(c.text)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for claim {c.id}: {e}")

    # Build list of similarity tuples
    pairs = []
    for v1_c in v1_claims:
        if not v1_c.embedding:
            continue
        for v2_c in v2_claims:
            if not v2_c.embedding:
                continue
            score = cosine_similarity(v1_c.embedding, v2_c.embedding)
            if score >= min_similarity:
                pairs.append((score, v1_c.id, v2_c.id))

    # Bipartite matching: sort descending by score
    pairs.sort(key=lambda x: x[0], reverse=True)

    matched_v1 = set()
    matched_v2 = set()
    mapping = {}

    for score, v1_id, v2_id in pairs:
        if v1_id not in matched_v1 and v2_id not in matched_v2:
            mapping[v1_id] = v2_id
            matched_v1.add(v1_id)
            matched_v2.add(v2_id)

    return mapping


# -------------------------------------------------------------
# Robust Fallback Paragraph Container matching
# -------------------------------------------------------------
def check_paragraph_match(
    claim_text: str,
    paragraph_text: str,
    embedding_service: EmbeddingService = None,
    claim_embedding: list[float] | None = None,
) -> bool:
    """
    Robust matching fallback chain:
      1. Exact containment (case-insensitive)
      2. SequenceMatcher text ratio check
      3. Semantic vector cosine similarity check
    """
    if not claim_text or not paragraph_text:
        return False

    # 1. Containment check
    if claim_text.lower() in paragraph_text.lower() or paragraph_text.lower() in claim_text.lower():
        return True

    # 2. SequenceMatcher similarity ratio
    ratio = difflib.SequenceMatcher(None, claim_text.lower(), paragraph_text.lower()).ratio()
    if ratio >= 0.7:
        return True

    # 3. Semantic similarity fallback
    if embedding_service and claim_embedding:
        try:
            para_emb = embedding_service.embed(paragraph_text)
            score = cosine_similarity(claim_embedding, para_emb)
            if score >= 0.75:
                return True
        except Exception as e:
            logger.debug(f"Failed semantic matching of paragraph to claim: {e}")

    return False


# -------------------------------------------------------------
# Socratic Issue State Transition Logic
# -------------------------------------------------------------
def advance_issue_status(
    current_status: str,
    is_changed: bool,
    is_unresolved: bool,
) -> tuple[str, int]:
    """
    Computes status transitions and escalation increments:
      - open + unchanged -> persistent (escalation=0)
      - open + changed (resolved) -> addressed (escalation=0)
      - open + changed (unresolved) -> persistent (escalation=0)
      - persistent + unchanged -> escalated (+1)
      - persistent + changed (resolved) -> addressed (escalation=0)
      - persistent + changed (unresolved) -> escalated (+1)
      - escalated + unchanged -> escalated (+1)
      - escalated + changed (resolved) -> addressed (escalation=0)
      - escalated + changed (unresolved) -> escalated (+1)
    """
    if current_status == "addressed":
        return "addressed", 0

    if not is_changed:
        if current_status == "open":
            return "persistent", 0
        else:
            return "escalated", 1

    # Section has been modified, check resolution outcome
    if not is_unresolved:
        return "addressed", 0

    # Section modified but unresolved
    if current_status == "open":
        return "persistent", 0
    else:
        return "escalated", 1


# -------------------------------------------------------------
# Gemini Resolution Re-analysis
# -------------------------------------------------------------
class ReanalysisResult(BaseModel):
    is_unresolved: bool = Field(
        description="True if the issue remains unresolved or poorly addressed, False if the modified text fully resolves the concern."
    )
    explanation: str = Field(
        description="Brief justification of the assessment."
    )


async def evaluate_issue_resolution(
    issue: Issue,
    new_paragraph_text: str,
    embedding_service: EmbeddingService = None,
) -> ReanalysisResult:
    """
    Calls Gemini to evaluate if the revision successfully addressed the flagged issue.
    """
    from google.genai import Client
    import os

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        return ReanalysisResult(
            is_unresolved=True,
            explanation="Local offline mode fallback: no Google Cloud Project configured."
        )

    client = Client(
        vertexai=True,
        project=project_id,
        location=os.environ.get("VERTEX_AI_LOCATION", "asia-south1"),
    )

    prompt = (
        f"You are an academic logic and evidence validator. Your task is to review if a revision "
        f"adequately addresses a previously flagged issue.\n\n"
        f"Flagged Issue Category: {issue.issue_type}\n"
        f"Concern Description: {issue.description}\n"
        f"Socratic Question Raised: {issue.question_text}\n\n"
        f"New Revised Paragraph Copy:\n\"{new_paragraph_text}\"\n\n"
        f"Does the issue still persist in this revised text, or has the user resolved/addressed it? "
        f"Answer is_unresolved=True if the concern remains unaddressed. "
        f"Answer is_unresolved=False if the revised copy makes reasonable, constructive progress."
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ReanalysisResult,
            ),
        )
        import json
        data = json.loads(response.text)
        return ReanalysisResult.model_validate(data)
    except Exception as e:
        logger.error(f"Failed to evaluate issue resolution via Gemini: {e}")
        return ReanalysisResult(
            is_unresolved=True,
            explanation=f"Error running Gemini reanalysis: {str(e)}"
        )


# -------------------------------------------------------------
# Main Analysis Loop
# -------------------------------------------------------------
async def analyze_revision_issues(
    repo: FirestoreRepository,
    document_id: str,
    v1_version_id: str,
    v2_version_id: str,
    v1_claims: list[Claim],
    v2_claims: list[Claim],
    changes: list[RevisionChange],
    embedding_service: EmbeddingService = None,
) -> list[Issue]:
    """
    Main Day 6 Revision Intelligence loop.
    Maps V1 claims to V2 claims, detects paragraph modifications via the robust fallback matching chain,
    evaluates changes using advance_issue_status/Gemini re-analysis, and records status transitions
    in detailed IssueEvents under Firestore.
    """
    # 1. Map V1 claims to V2 claims semantically
    claim_map = match_v1_to_v2_claims(v1_claims, v2_claims, embedding_service)

    # 2. Get active open/persistent/escalated issues of V1
    all_issues = repo.get_issues(document_id)
    v1_issues = [
        issue for issue in all_issues
        if issue.version_id == v1_version_id and issue.status != "addressed"
    ]

    processed_issues = []
    processed_events = []

    for issue in v1_issues:
        v2_claim_id = claim_map.get(issue.claim_id) if issue.claim_id else None

        # Look up the Claim object
        v1_claim = next((c for c in v1_claims if c.id == issue.claim_id), None) if issue.claim_id else None

        # Determine if paragraph containing the claim changed
        section_changed = False
        new_paragraph_text = ""

        for change in changes:
            if change.before:
                # Use the robust fallback match chain
                if check_paragraph_match(
                    claim_text=v1_claim.text if v1_claim else issue.section,
                    paragraph_text=change.before,
                    embedding_service=embedding_service,
                    claim_embedding=v1_claim.embedding if v1_claim else None,
                ):
                    if change.change_type in ["modified", "removed"]:
                        section_changed = True
                        new_paragraph_text = change.after or ""
                    break

        if not section_changed:
            # USER IGNORED: Escalate/mark persistent
            new_status, escalation_incr = advance_issue_status(
                current_status=issue.status,
                is_changed=False,
                is_unresolved=True,
            )
            explanation = "Issue paragraph remains completely unmodified across revisions."
        else:
            # USER MODIFIED: Re-evaluate!
            re_res = ReanalysisResult(is_unresolved=True, explanation="Unmodified placeholder")
            if new_paragraph_text:
                re_res = await evaluate_issue_resolution(
                    issue, new_paragraph_text, embedding_service
                )
            
            new_status, escalation_incr = advance_issue_status(
                current_status=issue.status,
                is_changed=True,
                is_unresolved=re_res.is_unresolved,
            )
            explanation = re_res.explanation

        # Build current Issue state
        updated_issue = Issue(
            id=issue.id,
            document_id=document_id,
            version_id=v2_version_id,
            claim_id=v2_claim_id or issue.claim_id,
            section=issue.section,
            issue_type=issue.issue_type,
            description=issue.description,
            question_text=issue.question_text,
            question_type=issue.question_type,
            status=new_status,
            first_detected_version=issue.first_detected_version,
            last_checked_version=v2_version_id,
            escalation_count=issue.escalation_count + escalation_incr,
            created_at=issue.created_at,
        )

        # Build high-fidelity tracking event
        event = IssueEvent(
            id=f"event-{uuid4()}",
            issue_id=issue.id,
            version_id=v2_version_id,
            previous_status=issue.status,
            new_status=new_status,
            event_type="ignored" if not section_changed else "re_analyzed",
            explanation=explanation,
        )

        processed_issues.append(updated_issue)
        processed_events.append(event)

    # Save to Firestore
    if processed_issues:
        repo.save_issues(document_id, processed_issues)
        repo.save_issue_events(document_id, processed_events)

    return processed_issues
