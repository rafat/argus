import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

from app.models.claim import Claim
from app.models.issue import Issue, IssueEvent
from app.tools.firestore import FirestoreRepository
from app.tools.revision_intelligence import (
    analyze_revision_issues,
    diff_paragraphs,
    RevisionChange,
    ReanalysisResult,
)


@pytest.mark.asyncio
async def test_day6_end_to_end_socratic_revision_lifecycle():
    """
    Day 6 End-to-End Acceptance Test:
      1. V1 Draft: Coaching session flags an evidence issue as 'open', logging a 'created' event.
      2. V2 Draft: User ignores the issue (paragraph unchanged). The revision engine advances status
         from 'open' to 'persistent' and logs an 'ignored' event.
      3. V3 Draft: User still ignores the issue. The revision engine advances status from
         'persistent' to 'escalated' (escalation_count=1) and logs an 'ignored' event.
    """
    mock_repo = MagicMock(spec=FirestoreRepository)
    document_id = "doc-E2E"
    v1_id = "ver-1"
    v2_id = "ver-2"
    v3_id = "ver-3"

    # --- PHASE 1: V1 Socratic Coaching creates Issue and Event ---
    v1_claim = Claim(
        id="c1",
        document_id=document_id,
        document_version=v1_id,
        text="Recommendation algorithms systematically increase political polarization.",
        evidence_cited=[],
        chapter="1",
        section="Paragraph 1",
        confidence=0.5,
        status="unsubstantiated",
        open_questions=[],
        embedding=[1.0, 0.0],
    )

    v1_issue = Issue(
        id="issue-001",
        document_id=document_id,
        version_id=v1_id,
        claim_id="c1",
        section="Paragraph 1",
        issue_type="evidence",
        description="Missing empirical meta-analysis citation.",
        question_text="Can you supply a peer-reviewed citation for polarization?",
        question_type="evidence",
        status="open",
        first_detected_version=v1_id,
        last_checked_version=v1_id,
    )

    v1_event = IssueEvent(
        id="event-001",
        issue_id="issue-001",
        version_id=v1_id,
        previous_status=None,
        new_status="open",
        event_type="created",
        explanation="Initial Socratic analysis findings."
    )

    assert v1_issue.status == "open"
    assert v1_event.new_status == "open"
    assert v1_event.event_type == "created"

    # --- PHASE 2: V2 Revision (User ignores paragraph) ---
    v2_claim = Claim(
        id="c1-v2",
        document_id=document_id,
        document_version=v2_id,
        text="Recommendation algorithms systematically increase political polarization.",
        evidence_cited=[],
        chapter="1",
        section="Paragraph 1",
        confidence=0.5,
        status="unsubstantiated",
        open_questions=[],
        embedding=[1.0, 0.0],
    )

    # Paragraph remains completely identical (unchanged)
    changes_v1_v2 = [
        RevisionChange(
            location="Paragraph 1",
            change_type="unchanged",
            before="Recommendation algorithms systematically increase political polarization.",
            after="Recommendation algorithms systematically increase political polarization.",
            similarity=1.0,
        )
    ]

    mock_repo.get_issues.return_value = [v1_issue]

    with patch("app.tools.revision_intelligence.evaluate_issue_resolution") as mock_eval:
        v2_issues = await analyze_revision_issues(
            repo=mock_repo,
            document_id=document_id,
            v1_version_id=v1_id,
            v2_version_id=v2_id,
            v1_claims=[v1_claim],
            v2_claims=[v2_claim],
            changes=changes_v1_v2,
        )

        assert len(v2_issues) == 1
        assert v2_issues[0].status == "persistent"
        assert v2_issues[0].last_checked_version == v2_id
        assert v2_issues[0].escalation_count == 0
        mock_eval.assert_not_called()

        # Capture the saved arguments
        saved_v2_issues = mock_repo.save_issues.call_args[0][1]
        saved_v2_events = mock_repo.save_issue_events.call_args[0][1]

        assert saved_v2_issues[0].status == "persistent"
        assert saved_v2_events[0].new_status == "persistent"
        assert saved_v2_events[0].previous_status == "open"
        assert saved_v2_events[0].event_type == "ignored"

    # --- PHASE 3: V3 Revision (User still ignores paragraph -> Escalates) ---
    v3_claim = Claim(
        id="c1-v3",
        document_id=document_id,
        document_version=v3_id,
        text="Recommendation algorithms systematically increase political polarization.",
        evidence_cited=[],
        chapter="1",
        section="Paragraph 1",
        confidence=0.5,
        status="unsubstantiated",
        open_questions=[],
        embedding=[1.0, 0.0],
    )

    changes_v2_v3 = [
        RevisionChange(
            location="Paragraph 1",
            change_type="unchanged",
            before="Recommendation algorithms systematically increase political polarization.",
            after="Recommendation algorithms systematically increase political polarization.",
            similarity=1.0,
        )
    ]

    # Reset mock and load the v2 persistent issue
    mock_repo.reset_mock()
    mock_repo.get_issues.return_value = [v2_issues[0]]

    with patch("app.tools.revision_intelligence.evaluate_issue_resolution") as mock_eval:
        v3_issues = await analyze_revision_issues(
            repo=mock_repo,
            document_id=document_id,
            v1_version_id=v2_id,
            v2_version_id=v3_id,
            v1_claims=[v2_claim],
            v2_claims=[v3_claim],
            changes=changes_v2_v3,
        )

        assert len(v3_issues) == 1
        assert v3_issues[0].status == "escalated"
        assert v3_issues[0].last_checked_version == v3_id
        assert v3_issues[0].escalation_count == 1
        mock_eval.assert_not_called()

        saved_v3_issues = mock_repo.save_issues.call_args[0][1]
        saved_v3_events = mock_repo.save_issue_events.call_args[0][1]

        assert saved_v3_issues[0].status == "escalated"
        assert saved_v3_issues[0].escalation_count == 1
        assert saved_v3_events[0].new_status == "escalated"
        assert saved_v3_events[0].previous_status == "persistent"
        assert saved_v3_events[0].event_type == "ignored"


@pytest.mark.asyncio
async def test_day6_end_to_end_socratic_revision_modified_resolution():
    """
    Day 6 End-to-End Acceptance Test (Resolution path):
      1. V1 Draft: Coaching flags an issue as 'open'.
      2. V2 Draft: User modifies the paragraph. Re-evaluation runs and resolves the issue ('addressed').
    """
    mock_repo = MagicMock(spec=FirestoreRepository)
    document_id = "doc-E2E-res"
    v1_id = "ver-1"
    v2_id = "ver-2"

    v1_claim = Claim(
        id="c1",
        document_id=document_id,
        document_version=v1_id,
        text="Causal claim text.",
        evidence_cited=[],
        chapter="1",
        section="Paragraph 1",
        confidence=0.5,
        status="unsubstantiated",
        open_questions=[],
        embedding=[1.0, 0.0],
    )

    v1_issue = Issue(
        id="issue-001",
        document_id=document_id,
        version_id=v1_id,
        claim_id="c1",
        section="Paragraph 1",
        issue_type="evidence",
        description="Missing citation.",
        question_text="Can you add a citation?",
        question_type="evidence",
        status="open",
        first_detected_version=v1_id,
        last_checked_version=v1_id,
    )

    mock_repo.get_issues.return_value = [v1_issue]

    v2_claim = Claim(
        id="c1-v2",
        document_id=document_id,
        document_version=v2_id,
        text="Causal claim text with a metadata citation (Study 2026).",
        evidence_cited=["Study 2026"],
        chapter="1",
        section="Paragraph 1",
        confidence=0.9,
        status="supported",
        open_questions=[],
        embedding=[1.0, 0.0],
    )

    changes_v1_v2 = [
        RevisionChange(
            location="Paragraph 1",
            change_type="modified",
            before="Causal claim text.",
            after="Causal claim text with a metadata citation (Study 2026).",
            similarity=0.85,
        )
    ]

    with patch(
        "app.tools.revision_intelligence.evaluate_issue_resolution",
        new_callable=AsyncMock,
        return_value=ReanalysisResult(is_unresolved=False, explanation="Citation successfully supplied."),
    ) as mock_eval:
        v2_issues = await analyze_revision_issues(
            repo=mock_repo,
            document_id=document_id,
            v1_version_id=v1_id,
            v2_version_id=v2_id,
            v1_claims=[v1_claim],
            v2_claims=[v2_claim],
            changes=changes_v1_v2,
        )

        assert len(v2_issues) == 1
        assert v2_issues[0].status == "addressed"
        mock_eval.assert_called_once()

        saved_v2_issues = mock_repo.save_issues.call_args[0][1]
        saved_v2_events = mock_repo.save_issue_events.call_args[0][1]

        assert saved_v2_issues[0].status == "addressed"
        assert saved_v2_events[0].new_status == "addressed"
        assert saved_v2_events[0].previous_status == "open"
        assert saved_v2_events[0].event_type == "re_analyzed"
