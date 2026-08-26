# Argus

Argus is an AI-assisted research integrity and argument-analysis platform. It
helps researchers inspect the claims in a document, understand how those claims
relate to one another, identify weaknesses, and improve the work through
Socratic coaching rather than ghostwriting.

Argus is designed around a simple principle:

> Help the researcher reason more clearly without replacing the researcher’s
> intellectual work.

## What Argus does

### Research-claim extraction

Argus accepts PDF and DOCX research documents and extracts their central
claims. Each claim can be examined as part of the document’s larger argument
rather than as isolated text.

### Multi-agent argument analysis

Specialized agents analyze different dimensions of a document:

- Evidence quality and empirical support
- Logical coherence and reasoning flaws
- Socratic questions that expose assumptions and gaps
- Relationships and conflicts between claims
- Overall argument structure

The resulting claims and relationships are presented as an interactive
argument graph.

### Semantic claim retrieval

Claim embeddings are indexed through Vertex AI Agent Retrieval / Vector Search.
This allows Argus to find semantically related claims and identify potential
conflicts or duplicated reasoning across a document and its revisions.

Firestore stores the canonical document, claim, conflict, issue, and revision
records. Vector Search is used as the semantic retrieval layer rather than the
system of record.

### Revision intelligence

Argus treats a document as a sequence of versions. It can compare revisions at
the paragraph level, match changed text to previously analyzed claims, and
track whether an issue was resolved.

Issues can move through the following lifecycle:

```text
OPEN → ADDRESSED
     → PERSISTENT → ESCALATED
```

This makes it possible to distinguish between an issue that was fixed, one that
was left unchanged, and one that remained unresolved across multiple versions.

### Adaptive Socratic coaching

Researchers can ask questions about a document, claim, or tracked issue. Argus
combines the current issue context with revision history and adaptive coaching
weights to provide targeted feedback.

The coaching workflow is intended to guide the researcher toward stronger
reasoning, better evidence, and clearer assumptions. It does not provide
submission-ready prose or write replacement sections on the researcher’s
behalf.

### Content safety and integrity guardrails

Argus treats uploaded documents as untrusted content. Text inside a document is
data to analyze, never an instruction that can override the agent policies.

Guardrails operate at three boundaries:

1. User input, to detect prompt injection and integrity-policy bypasses.
2. Document content, to identify malicious instructions and suspicious text.
3. Generated output, to prevent unsafe responses or ghostwritten submission
   content from reaching the user.

Production deployments can use Google Model Armor for managed content
inspection. Argus also retains an application-level integrity interceptor for
Argus-specific coaching and anti-ghostwriting policy decisions.

## Architecture

```text
User browser
    │ HTTPS
    ▼
React/Vite frontend
    │ HTTPS
    ▼
FastAPI API on Cloud Run
    │
    ├── Cloud Storage       Uploaded PDF/DOCX files
    ├── Firestore            Documents, claims, issues, and revisions
    ├── Vertex AI            Gemini analysis and embeddings
    ├── Vector Search        Semantic claim retrieval
    ├── Model Armor          Production content guardrails
    └── Pub/Sub              Asynchronous document processing
```

Uploads return immediately and are processed asynchronously. The frontend
polls document state while the backend parses the document, extracts claims,
generates embeddings, analyzes conflicts, evaluates issues, and persists the
result.

## Main user experience

The frontend provides:

- Document and version selection
- Processing-state feedback
- Interactive circular argument graph
- Expandable claim details
- Claim support and conflict visualization
- Issue tracking across revisions
- Paragraph-level revision differences
- Addressed, persistent, and escalated issue states
- Socratic coaching for selected claims and issues

## Technology

- Python 3.11+
- FastAPI and Uvicorn
- Google Gen AI SDK
- Gemini through Vertex AI
- Google Agent Development Kit (ADK)
- Firestore
- Cloud Storage
- Pub/Sub
- Vertex AI Agent Retrieval / Vector Search
- Model Armor
- React and Vite
- React Flow
- Cloud Run

## Repository structure

```text
argus/
├── backend/
│   ├── app/
│   │   ├── agents/          Specialist and coordinator agents
│   │   ├── guardrails/      Local and Model Armor guardrails
│   │   ├── models/          Domain models
│   │   ├── nodes/           Workflow nodes
│   │   ├── tools/           Storage, retrieval, analysis, and graph tools
│   │   ├── workflows/       Document and coaching workflows
│   │   └── tests/            Unit, security, and integration tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/                 React application and state management
│   ├── Dockerfile
│   ├── cloudbuild.yaml
│   └── nginx.conf
├── deployment.txt           Current deployment and operations notes
├── setup.md                 Local setup and deployment guide
└── .env.example             Configuration variable reference
```

## API capabilities

The backend exposes APIs for:

- Health and document listing
- PDF/DOCX upload and asynchronous processing
- Argument graph retrieval
- Claim and issue retrieval
- Version history and paragraph diffs
- Issue-event history across revisions
- Socratic coaching
- Authenticated Pub/Sub document-processing delivery

The browser communicates with the API only. Privileged services such as
Firestore, Cloud Storage, Vertex AI, Vector Search, Model Armor, and Pub/Sub
are accessed by the backend.

## Documentation

- [Setup and deployment guide](setup.md)
- [Current deployment and operations notes](deployment.txt)

