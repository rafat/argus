import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from app.models.claim import Claim
from app.models.document import DocumentRecord
from app.models.issue import Issue, IssueEvent
from app.tools.firestore import FirestoreRepository
from app.tools.revision_intelligence import (
    diff_paragraphs,
    split_paragraphs,
    match_v1_to_v2_claims,
    analyze_revision_issues,
    evaluate_issue_resolution,
    advance_issue_status,
    ReanalysisResult,
    RevisionChange,
)
from app.tools.adaptive_coaching import calculate_coaching_weights, inject_adaptive_instructions
from app.tools.pubsub import PubSubBroker


# -------------------------------------------------------------
# 1. Paragraph Splitting & Textual Diff Tests
# -------------------------------------------------------------
def test_split_paragraphs():
    text = "Paragraph A.\n\nParagraph B.\nParagraph B continuation.\n\nParagraph C."
    paras = split_paragraphs(text)
    assert len(paras) == 3
    assert paras[0] == "Paragraph A."
    assert paras[1] == "Paragraph B. Paragraph B continuation."
    assert paras[2] == "Paragraph C."


def test_diff_paragraphs_identical():
    text = "First paragraph.\n\nSecond paragraph."
    changes = diff_paragraphs(text, text)
    assert len(changes) == 2
    assert all(c.change_type == "unchanged" for c in changes)
    assert all(c.similarity == 1.0 for c in changes)


def test_diff_paragraphs_modifications():
    v1 = "Recommendation algorithms systematically increase polarization."
    v2 = "Recommendation algorithms can increase polarization under some conditions."
    changes = diff_paragraphs(v1, v2)
    assert len(changes) == 1
    assert changes[0].change_type == "modified"
    assert changes[0].before == v1
    assert changes[0].after == v2
    assert 0.0 < changes[0].similarity < 1.0


def test_diff_paragraphs_added():
    v1 = "Paragraph one."
    v2 = "Paragraph one.\n\nParagraph two (added)."
    changes = diff_paragraphs(v1, v2)
    assert len(changes) == 2
    assert changes[0].change_type == "unchanged"
    assert changes[1].change_type == "added"
    assert changes[1].before is None
    assert changes[1].after == "Paragraph two (added)."


def test_diff_paragraphs_removed():
    v1 = "Paragraph one.\n\nParagraph two."
    v2 = "Paragraph one."
    changes = diff_paragraphs(v1, v2)
    assert len(changes) == 2
    assert changes[0].change_type == "unchanged"
    assert changes[1].change_type == "removed"
    assert changes[1].before == "Paragraph two."
    assert changes[1].after is None


# -------------------------------------------------------------
# 2. Semantic Claim Matching Tests (including 1-to-1 matching)
# -------------------------------------------------------------
def test_match_v1_to_v2_claims():
    v1_claim = Claim(
        id="c1", document_id="doc-123", document_version="v1",
        text="Algorithms increase political polarization.",
        evidence_cited=[], chapter="1", section="1", confidence=0.8,
        status="unsubstantiated", open_questions=[]
    )
    v2_claim = Claim(
        id="c2", document_id="doc-123", document_version="v2",
        text="Algorithms can amplify political polarization.",
        evidence_cited=[], chapter="1", section="1", confidence=0.9,
        status="unsubstantiated", open_questions=[]
    )
    v1_claim.embedding = [1.0, 0.0, 0.0]
    v2_claim.embedding = [0.95, 0.05, 0.0]

    mapping = match_v1_to_v2_claims([v1_claim], [v2_claim])
    assert mapping["c1"] == "c2"


def test_claim_matching_one_to_one():
    # Two V1 claims mapping to the same V2 claim: greedy matching must constrain to 1-to-1
    c1 = Claim(
        id="v1_c1", document_id="doc", document_version="v1",
        text="C1 text", evidence_cited=[], chapter="1", section="1", confidence=0.5,
        status="unsubstantiated", open_questions=[]
    )
    c2 = Claim(
        id="v1_c2", document_id="doc", document_version="v1",
        text="C2 text", evidence_cited=[], chapter="1", section="1", confidence=0.5,
        status="unsubstantiated", open_questions=[]
    )
    v2_x = Claim(
        id="v2_x", document_id="doc", document_version="v2",
        text="X text", evidence_cited=[], chapter="1", section="1", confidence=0.5,
        status="unsubstantiated", open_questions=[]
    )
    v2_y = Claim(
        id="v2_y", document_id="doc", document_version="v2",
        text="Y text", evidence_cited=[], chapter="1", section="1", confidence=0.5,
        status="unsubstantiated", open_questions=[]
    )

    c1.embedding = [1.0, 0.0]
    c2.embedding = [0.9, 0.1]
    v2_x.embedding = [1.0, 0.0]  # Closest to c1
    v2_y.embedding = [0.8, 0.2]  # Closest to c2

    mapping = match_v1_to_v2_claims([c1, c2], [v2_x, v2_y])
    
    # 1-to-1 matching must assign c1 to v2_x and c2 to v2_y
    assert mapping["v1_c1"] == "v2_x"
    assert mapping["v1_c2"] == "v2_y"


# -------------------------------------------------------------
# 3. Socratic Issue State Transition Tests
# -------------------------------------------------------------
def test_advance_issue_status():
    # Test open transitions
    assert advance_issue_status("open", is_changed=False, is_unresolved=True) == ("persistent", 0)
    assert advance_issue_status("open", is_changed=True, is_unresolved=False) == ("addressed", 0)
    assert advance_issue_status("open", is_changed=True, is_unresolved=True) == ("persistent", 0)

    # Test persistent transitions
    assert advance_issue_status("persistent", is_changed=False, is_unresolved=True) == ("escalated", 1)
    assert advance_issue_status("persistent", is_changed=True, is_unresolved=False) == ("addressed", 0)
    assert advance_issue_status("persistent", is_changed=True, is_unresolved=True) == ("escalated", 1)

    # Test escalated transitions
    assert advance_issue_status("escalated", is_changed=False, is_unresolved=True) == ("escalated", 1)
    assert advance_issue_status("escalated", is_changed=True, is_unresolved=False) == ("addressed", 0)
    assert advance_issue_status("escalated", is_changed=True, is_unresolved=True) == ("escalated", 1)


# -------------------------------------------------------------
# 4. Issue Escalation & Event History Integration Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_analyze_revision_issues_ignored_feedback():
    """Verify that if the user does NOT modify a paragraph, issues escalate/persist and emit Event logs."""
    mock_repo = MagicMock(spec=FirestoreRepository)

    v1_issue = Issue(
        id="issue-001",
        document_id="doc-123",
        version_id="v1",
        claim_id="c1",
        section="Paragraph 1",
        issue_type="evidence",
        description="Insufficient empirical evidence for causal claim.",
        question_text="What studies prove this?",
        question_type="evidence",
        status="open",
        first_detected_version="v1",
        last_checked_version="v1",
    )

    mock_repo.get_issues.return_value = [v1_issue]

    v1_claim = Claim(
        id="c1", document_id="doc-123", document_version="v1",
        text="Unmodified causal claim text here.",
        evidence_cited=[], chapter="1", section="1", confidence=0.8,
        status="unsubstantiated", open_questions=[], embedding=[1.0, 0.0],
    )
    v2_claim = Claim(
        id="c2", document_id="doc-123", document_version="v2",
        text="Unmodified causal claim text here.",
        evidence_cited=[], chapter="1", section="1", confidence=0.8,
        status="unsubstantiated", open_questions=[], embedding=[1.0, 0.0],
    )

    # Paragraph remains unchanged
    changes = [
        RevisionChange(
            before="Unmodified causal claim text here.",
            after="Unmodified causal claim text here.",
            change_type="unchanged",
            location="Paragraph 1",
        )
    ]

    with patch("app.tools.revision_intelligence.evaluate_issue_resolution") as mock_eval:
        updated_issues = await analyze_revision_issues(
            repo=mock_repo,
            document_id="doc-123",
            v1_version_id="v1",
            v2_version_id="v2",
            v1_claims=[v1_claim],
            v2_claims=[v2_claim],
            changes=changes,
        )

        assert len(updated_issues) == 1
        assert updated_issues[0].status == "persistent"
        assert updated_issues[0].last_checked_version == "v2"
        mock_eval.assert_not_called()
        
        # Verify both issues and events were persisted
        mock_repo.save_issues.assert_called_once()
        mock_repo.save_issue_events.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_revision_issues_modified_resolved():
    """Verify that if the user modifies a paragraph, the re-analysis runs and records events."""
    mock_repo = MagicMock(spec=FirestoreRepository)

    v1_issue = Issue(
        id="issue-001",
        document_id="doc-123",
        version_id="v1",
        claim_id="c1",
        section="Paragraph 1",
        issue_type="evidence",
        description="Insufficient empirical evidence for causal claim.",
        question_text="What studies prove this?",
        question_type="evidence",
        status="open",
        first_detected_version="v1",
        last_checked_version="v1",
    )

    mock_repo.get_issues.return_value = [v1_issue]

    v1_claim = Claim(
        id="c1", document_id="doc-123", document_version="v1",
        text="Unmodified causal claim text.",
        evidence_cited=[], chapter="1", section="1", confidence=0.8,
        status="unsubstantiated", open_questions=[], embedding=[1.0, 0.0],
    )
    v2_claim = Claim(
        id="c2", document_id="doc-123", document_version="v2",
        text="This is a completely rewritten paragraph with a cited meta-analysis study.",
        evidence_cited=["Study 2026"], chapter="1", section="1", confidence=0.9,
        status="supported", open_questions=[], embedding=[0.8, 0.6],
    )

    # Paragraph was modified
    changes = [
        RevisionChange(
            before="Unmodified causal claim text.",
            after="This is a completely rewritten paragraph with a cited meta-analysis study.",
            change_type="modified",
            location="Paragraph 1",
        )
    ]

    # Mock Gemini evaluation to return resolved (is_unresolved=False)
    with patch(
        "app.tools.revision_intelligence.evaluate_issue_resolution",
        new_callable=AsyncMock,
        return_value=ReanalysisResult(is_unresolved=False, explanation="Successfully added study citation."),
    ) as mock_eval:
        updated_issues = await analyze_revision_issues(
            repo=mock_repo,
            document_id="doc-123",
            v1_version_id="v1",
            v2_version_id="v2",
            v1_claims=[v1_claim],
            v2_claims=[v2_claim],
            changes=changes,
        )

        assert len(updated_issues) == 1
        assert updated_issues[0].status == "addressed"
        mock_eval.assert_called_once()
        mock_repo.save_issues.assert_called_once()
        mock_repo.save_issue_events.assert_called_once()


# -------------------------------------------------------------
# 5. Adaptive Weight Calculation Tests
# -------------------------------------------------------------
def test_calculate_coaching_weights():
    mock_repo = MagicMock(spec=FirestoreRepository)

    # Mock historical issues with different outcomes to test adaptivity
    issues = [
        Issue(
            id="1", document_id="doc", version_id="v1", issue_type="evidence",
            question_type="evidence", status="addressed", first_detected_version="v1", last_checked_version="v2",
            description="dummy"
        ),
        Issue(
            id="2", document_id="doc", version_id="v1", issue_type="logic",
            question_type="logic", status="persistent", first_detected_version="v1", last_checked_version="v2",
            description="dummy"
        ),
        Issue(
            id="3", document_id="doc", version_id="v1", issue_type="socratic",
            question_type="socratic", status="addressed", first_detected_version="v1", last_checked_version="v2",
            description="dummy"
        ),
    ]
    mock_repo.get_issues.return_value = issues

    weights = calculate_coaching_weights(mock_repo, "doc")
    
    # Assert evidence (1/1 success = 1.0 effectiveness) has more weight than logic (0/1 success = 0.0 effectiveness)
    assert weights["evidence"] > weights["logic"]
    assert sum(weights.values()) == pytest.approx(1.0)

    # Verify helper outputs proper adaptive coaching instructions
    instr = inject_adaptive_instructions(weights)
    assert "ADAPTIVE COACHING INJECTION" in instr


# -------------------------------------------------------------
# 6. Pub/Sub Broker Core Delivery Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_pubsub_broker_event_propagation():
    broker = PubSubBroker()
    delivered_payloads = []

    async def mock_callback(**kwargs):
        delivered_payloads.append(kwargs)

    broker.subscribe("test.topic", mock_callback)
    broker.publish("test.topic", key_a="val_a", key_b="val_b")

    # Yield control to allow async task loop to run
    await asyncio.sleep(0.05)

    assert len(delivered_payloads) == 1
    assert delivered_payloads[0]["key_a"] == "val_a"
    assert delivered_payloads[0]["key_b"] == "val_b"

