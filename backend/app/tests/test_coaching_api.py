import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime

from app.main import app
from app.models.document import DocumentRecord
from app.models.claim import Claim
from app.models.conflict import Conflict
from app.workflows.coaching_workflow import CoachingResult, _prepare_synthesis_inputs, build_coaching_workflow
from app.agents.socratic import SocraticQuestions
from app.agents.evidence import EvidenceAnalysis
from app.agents.argument import ArgumentAnalysis

client = TestClient(app)


def test_coaching_workflow_builds_with_adk_25_schema_validation():
    workflow = build_coaching_workflow()
    assert workflow.name == "collaborative_coaching_workflow"


# -------------------------------------------------------------
# Test 1: Normal Claim Coaching
# -------------------------------------------------------------
@patch("app.main.run_coaching_workflow")
def test_coaching_api_normal_claim_coaching(mock_run_workflow):
    """Verify normal claim coaching with valid claim id operates successfully and loads context."""
    mock_run_workflow.return_value = CoachingResult(
        coaching_feedback="### Socratic Reflections\nHave you verified this?",
        socratic_questions=["Question A?"],
        evidence_findings="Unsupported empirical claims.",
        evidence_suggestions=["Cite source X."],
        logical_flaws=["Circular premise logic."],
        coherence_score=0.8
    )

    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document.return_value = DocumentRecord(
            id="test-doc",
            version_id="v-1",
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="processed",
        )

        mock_repo.get_claim.return_value = Claim(
            id="claim-1",
            document_id="test-doc",
            document_version="v-1",
            text="AI increases user polarities.",
            evidence_cited=[],
            chapter="1",
            section="1.2",
            confidence=0.7,
            status="unsubstantiated",
            open_questions=["Is there a citation?"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Mock the semantic classifier bypass
        from app.nodes.integrity import IntentClassification
        mock_classification = {"classification": IntentClassification(is_ghostwriting=False, reason="Coaching inquiry")}
        async def mock_generator(*args, **kwargs):
            class MockNodeInfo:
                name = "integrity_classifier"
            class MockEvent:
                node_info = MockNodeInfo()
                output = mock_classification
            yield MockEvent()

        with patch("google.adk.runners.Runner.run_async", side_effect=mock_generator):
            response = client.post(
                "/documents/test-doc/coaching",
                json={
                    "user_prompt": "Help me explore assumptions on my polarization claim.",
                    "selected_claim_id": "claim-1",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "allowed"
            assert "Socratic Reflections" in data["coaching_response"]
            assert data["structured_coaching"]["coherence_score"] == 0.8

            mock_repo.get_claim.assert_called_once_with("test-doc", "claim-1")
            mock_run_workflow.assert_called_once()
            # Assert context parameter contained selected claim text
            context_arg = mock_run_workflow.call_args[0][1]
            assert "AI increases user polarities" in context_arg


# -------------------------------------------------------------
# Test 2: Conflict Coaching
# -------------------------------------------------------------
@patch("app.main.run_coaching_workflow")
def test_coaching_api_conflict_coaching(mock_run_workflow):
    """Verify conflict coaching loads both claims text into agent context."""
    mock_run_workflow.return_value = CoachingResult(
        coaching_feedback="### Contradiction Review\nThese points clash.",
        socratic_questions=[],
        evidence_findings="",
        evidence_suggestions=[],
        logical_flaws=[],
        coherence_score=0.5
    )

    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document.return_value = DocumentRecord(
            id="test-doc",
            version_id="v-1",
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="processed",
        )

        mock_repo.get_conflicts.return_value = [
            Conflict(
                id="conflict-1",
                document_id="test-doc",
                claim_a_id="claim-1",
                claim_b_id="claim-2",
                claim_a_text="Claim A: Recommendations increase polarization.",
                claim_b_text="Claim B: Algorithms reduce extreme echo groups.",
                explanation="Logical conflict between increase and reduce.",
                severity="high",
                confidence=0.9,
                created_at=datetime.utcnow()
            )
        ]

        from app.nodes.integrity import IntentClassification
        mock_classification = {"classification": IntentClassification(is_ghostwriting=False, reason="Conflict evaluation")}
        async def mock_generator(*args, **kwargs):
            class MockNodeInfo:
                name = "integrity_classifier"
            class MockEvent:
                node_info = MockNodeInfo()
                output = mock_classification
            yield MockEvent()

        with patch("google.adk.runners.Runner.run_async", side_effect=mock_generator):
            response = client.post(
                "/documents/test-doc/coaching",
                json={
                    "user_prompt": "Help me resolve the algorithmic contradiction.",
                    "selected_conflict_id": "conflict-1",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "allowed"
            
            # Assert context parameter contained Claim A, Claim B, and explanation
            context_arg = mock_run_workflow.call_args[0][1]
            assert "Claim A: Recommendations increase polarization." in context_arg
            assert "Claim B: Algorithms reduce extreme echo groups." in context_arg
            assert "Logical conflict between increase and reduce." in context_arg


# -------------------------------------------------------------
# Test 3: General Document Coaching
# -------------------------------------------------------------
@patch("app.main.run_coaching_workflow")
def test_coaching_api_general_document_coaching(mock_run_workflow):
    """Verify general coaching (neither selection) provides correct context string."""
    mock_run_workflow.return_value = CoachingResult(
        coaching_feedback="### General Feedback\nExplore the overall flow.",
        socratic_questions=[],
        evidence_findings="",
        evidence_suggestions=[],
        logical_flaws=[],
        coherence_score=1.0
    )

    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document.return_value = DocumentRecord(
            id="test-doc",
            version_id="v-1",
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="processed",
        )

        from app.nodes.integrity import IntentClassification
        mock_classification = {"classification": IntentClassification(is_ghostwriting=False, reason="General check")}
        async def mock_generator(*args, **kwargs):
            class MockNodeInfo:
                name = "integrity_classifier"
            class MockEvent:
                node_info = MockNodeInfo()
                output = mock_classification
            yield MockEvent()

        with patch("google.adk.runners.Runner.run_async", side_effect=mock_generator):
            response = client.post(
                "/documents/test-doc/coaching",
                json={"user_prompt": "What broad questions should I ask?"},
            )

            assert response.status_code == 200
            mock_run_workflow.assert_called_once()
            context_arg = mock_run_workflow.call_args[0][1]
            assert "General Document Review" in context_arg


# -------------------------------------------------------------
# Test 4: Both Claim & Conflict Selected (raises 422)
# -------------------------------------------------------------
def test_coaching_api_both_selected_validation():
    """Verify Pydantic model validator prevents specifying both selection IDs (raises 422)."""
    response = client.post(
        "/documents/test-doc/coaching",
        json={
            "user_prompt": "Hello",
            "selected_claim_id": "claim-123",
            "selected_conflict_id": "conflict-123",
        },
    )
    assert response.status_code == 422
    assert "Specify either selected_claim_id or selected_conflict_id, not both." in response.text


# -------------------------------------------------------------
# Test 5: Unknown Document
# -------------------------------------------------------------
def test_coaching_api_unknown_document():
    """Verify 404 is returned for unknown document request keys."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document.return_value = None

        response = client.post(
            "/documents/unknown-doc/coaching",
            json={"user_prompt": "Hello"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"


# -------------------------------------------------------------
# Test 6: Integrity Interception Does Not Invoke Socratic Workflow
# -------------------------------------------------------------
@patch("app.main.run_coaching_workflow")
def test_coaching_api_integrity_interception_bypasses_workflow(mock_run_workflow):
    """Verify that intercepted prompts (blocked) NEVER trigger the multi-agent Socratic workflow."""
    with patch("app.main.FirestoreRepository") as MockRepository:
        mock_repo = MockRepository.return_value
        mock_repo.get_document.return_value = DocumentRecord(
            id="test-doc",
            version_id="v-1",
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=100,
            status="processed",
        )

        response = client.post(
            "/documents/test-doc/coaching",
            json={"user_prompt": "Write section 3.2 for me."},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "intercepted"
        
        # Verify workflow coordinator was completely bypassed (never called!)
        mock_run_workflow.assert_not_called()
        mock_repo.save_interception.assert_called_once()


# -------------------------------------------------------------
# Test 7: Specialist Outputs Survive ADK Serialization
# -------------------------------------------------------------
def test_prepare_synthesis_inputs_dict_survives_adk_boundary():
    """Verify _prepare_synthesis_inputs successfully rehydrates raw dictionary structures crossing the ADK boundary."""
    class MockContextState(dict):
        @property
        def state(self):
            return self

    ctx = MockContextState()
    
    # Simulate dictionary payloads returned after crossing ADK pipeline state transitions
    ctx["socratic_res"] = {"questions": ["Unpack premise A?", "Verify citation B?"]}
    ctx["evidence_res"] = {"findings": "Evidentiary gaps verified.", "suggestions": ["Check census database."]}
    ctx["argument_res"] = {"logical_flaws": ["Affirming the consequent."], "coherence_score": 0.45}

    result = _prepare_synthesis_inputs(ctx, {})
    assert result == {}

    # Verify rehydration correctly populated context inputs
    assert "Unpack premise A?" in ctx["socratic_output"]
    assert "Verify citation B?" in ctx["socratic_output"]
    assert "Evidentiary gaps verified." in ctx["evidence_output"]
    assert "Check census database." in ctx["evidence_output"]
    assert "Affirming the consequent." in ctx["argument_output"]
    assert "Coherence Score: 0.45" in ctx["argument_output"]
