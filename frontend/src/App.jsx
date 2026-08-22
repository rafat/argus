import React, { useCallback, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { useArgusStore } from './store/useArgusStore';
import ClaimNode from './components/ClaimNode';
import ConflictEdge from './components/ConflictEdge';
import './App.css';

// Map custom nodes and edges
const nodeTypes = {
  claimNode: ClaimNode,
};

const edgeTypes = {
  conflictEdge: ConflictEdge,
};

function App() {
  const {
    documents,
    selectedDocumentId,
    graphData,
    selectedNode,
    selectedEdge,
    isProcessing,
    uploadStatus,
    error,
    selectDocument,
    uploadDocument,
    setSelectedNode,
    setSelectedEdge,
    clearSelection,
  } = useArgusStore();

  const fileInputRef = useRef(null);

  // File upload trigger
  const handleUploadClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadDocument(file);
    }
  };

  // Node selection triggers
  const onNodeClick = useCallback((event, node) => {
    setSelectedNode(node);
  }, [setSelectedNode]);

  // Edge selection triggers
  const onEdgeClick = useCallback((event, edge) => {
    setSelectedEdge(edge);
  }, [setSelectedEdge]);

  // Clear selections on blank canvas click
  const onPaneClick = useCallback(() => {
    clearSelection();
  }, [clearSelection]);

  const activeDoc = documents.find((d) => d.id === selectedDocumentId);

  // Compute stats for current document
  const totalClaims = graphData.nodes.length;
  const totalConflicts = graphData.edges.length;
  const unsubstantiatedClaims = graphData.nodes.filter(
    (n) => n.data?.status === 'unsubstantiated'
  ).length;

  return (
    <div className="app-container">
      {/* 1. Header */}
      <header className="app-header">
        <div className="logo-container">
          <span className="logo-icon">👁️</span>
          <span className="logo-text">ARGUS</span>
        </div>
        <div className="header-status">
          {activeDoc ? (
            <span>Analyzing: <strong>{activeDoc.filename}</strong></span>
          ) : (
            <span>Please upload a document to begin Socratic analysis</span>
          )}
        </div>
      </header>

      {/* 2. Sidebar Pane */}
      <aside className="app-sidebar">
        {/* Upload Zone */}
        <div className="sidebar-section">
          <h3 className="sidebar-section-title">Ingest Document</h3>
          <div className="upload-zone" onClick={handleUploadClick}>
            <span className="upload-icon">📥</span>
            <span className="upload-text">Upload PDF or DOCX</span>
            <span className="upload-subtext">Supports analytical papers up to 80 pages</span>
          </div>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".pdf,.docx"
            className="file-input-hidden"
          />
        </div>

        {/* Selected Document Stats */}
        {selectedDocumentId && (
          <div className="sidebar-section">
            <h3 className="sidebar-section-title">Document Stats</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div>Total Claims: <strong>{totalClaims}</strong></div>
              <div>Conflicts: <strong style={{ color: 'var(--color-danger)' }}>{totalConflicts}</strong></div>
              <div>Needs Evidence: <strong style={{ color: 'var(--color-warning)' }}>{unsubstantiatedClaims}</strong></div>
            </div>
          </div>
        )}

        {/* Document List */}
        <div className="sidebar-section" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <h3 className="sidebar-section-title">Uploaded Drafts</h3>
          <ul className="document-list" style={{ flex: 1, overflowY: 'auto' }}>
            {documents.length === 0 ? (
              <li style={{ fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '20px' }}>
                No drafts processed yet.
              </li>
            ) : (
              documents.map((doc) => (
                <li
                  key={doc.id}
                  className={`document-item ${selectedDocumentId === doc.id ? 'active' : ''}`}
                  onClick={() => selectDocument(doc.id)}
                >
                  <span className="doc-name" title={doc.filename}>{doc.filename}</span>
                  <span className="doc-meta">
                    {new Date(doc.created_at).toLocaleDateString()} &bull; {(doc.size_bytes / 1024).toFixed(0)} KB
                  </span>
                </li>
              ))
            )}
          </ul>
        </div>
      </aside>

      {/* 3. Main Canvas (React Flow) */}
      <main className="app-canvas">
        {isProcessing && (
          <div className="canvas-loading-overlay">
            <div className="spinner"></div>
            <div className="loading-status">{uploadStatus || 'Processing argument network...'}</div>
            <div className="loading-subtext">Executing ADK 2 agent graphs & verifying contradictions</div>
          </div>
        )}

        {error && (
          <div className="canvas-loading-overlay" style={{ gap: '12px' }}>
            <span style={{ fontSize: '32px' }}>⚠️</span>
            <div className="loading-status" style={{ color: 'var(--color-danger)' }}>Processing Error</div>
            <div className="loading-subtext" style={{ maxWidth: '400px', textAlign: 'center' }}>{error}</div>
            <button 
              className="socratic-btn" 
              style={{ marginTop: '12px', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}
              onClick={clearSelection}
            >
              Dismiss
            </button>
          </div>
        )}

        {selectedDocumentId ? (
          <ReactFlow
            nodes={graphData.nodes}
            edges={graphData.edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            fitView
          >
            <Background color="#2b2b35" gap={16} size={1} />
            <Controls />
            <MiniMap 
              nodeColor={(n) => (n.data?.status === 'supported' ? '#10b981' : '#f59e0b')} 
              maskColor="rgba(15, 15, 17, 0.6)"
              bgColor="#16161a"
            />
          </ReactFlow>
        ) : (
          <div className="canvas-loading-overlay" style={{ background: 'transparent' }}>
            <span style={{ fontSize: '48px' }}>🕸️</span>
            <div className="loading-status" style={{ fontSize: '18px' }}>Visualize Your Argument Graph</div>
            <div className="loading-subtext" style={{ maxWidth: '340px', textAlign: 'center' }}>
              Upload a document on the left. We will extract claims, match evidence, and layout contradictions in real-time.
            </div>
          </div>
        )}
      </main>

      {/* 4. Details Pane */}
      <section className="app-details">
        {selectedNode ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="details-header">
              <span className="details-location">
                {selectedNode.data?.chapter || 'Chapter'} &bull; {selectedNode.data?.section || 'Section'}
              </span>
              <h2 className="details-title">Claim Highlight</h2>
            </div>

            <div className="details-section">
              <span className="details-section-title">Extracted Text</span>
              <div className="details-text-box">{selectedNode.data?.text}</div>
            </div>

            <div className="details-section">
              <span className="details-section-title">Cited Evidence</span>
              {selectedNode.data?.evidence_cited && selectedNode.data.evidence_cited.length > 0 ? (
                <ul className="details-list">
                  {selectedNode.data.evidence_cited.map((evidence, idx) => (
                    <li key={idx} className="details-list-item">{evidence}</li>
                  ))}
                </ul>
              ) : (
                <div className="details-text-box" style={{ color: 'var(--color-warning)', borderStyle: 'dashed' }}>
                  No explicit external evidence cited in this draft.
                </div>
              )}
            </div>

            <div className="details-section">
              <span className="details-section-title">Open Questions</span>
              {selectedNode.data?.open_questions && selectedNode.data.open_questions.length > 0 ? (
                <ul className="details-list">
                  {selectedNode.data.open_questions.map((q, idx) => (
                    <li key={idx} className="details-list-item" style={{ color: '#fbcfe8' }}>{q}</li>
                  ))}
                </ul>
              ) : (
                <div className="details-text-box" style={{ color: 'var(--text-muted)' }}>
                  No unresolved structural questions detected.
                </div>
              )}
            </div>

            <div className="socratic-coaching-box">
              <span className="socratic-title">💡 Socratic Coaching Partner</span>
              <p className="socratic-text">
                Explore structural weaknesses, expand missing assumptions, or challenge other parts of your draft.
              </p>
              <button className="socratic-btn" onClick={() => alert("Socratic team activation coming on Day 5!")}>
                Trigger Socratic Team
              </button>
            </div>
          </div>
        ) : selectedEdge ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="details-header">
              <span className="details-location" style={{ color: 'var(--color-danger)' }}>
                CONTRADICTION &bull; SEVERITY: {selectedEdge.data?.severity?.toUpperCase() || 'HIGH'}
              </span>
              <h2 className="details-title">Argument conflict</h2>
            </div>

            <div className="details-section">
              <span className="details-section-title">Socratic Explanation</span>
              <div className="details-text-box" style={{ borderColor: 'rgba(239, 68, 68, 0.25)', borderLeft: '4px solid var(--color-danger)' }}>
                {selectedEdge.data?.explanation || 'A direct logical conflict was verified between these claims.'}
              </div>
            </div>

            <div className="details-section">
              <span className="details-section-title">Verification Confidence</span>
              <div className="details-text-box">
                Gemini Verification Confidence: <strong>{((selectedEdge.data?.confidence || 0) * 100).toFixed(0)}%</strong>
              </div>
            </div>

            <div className="socratic-coaching-box">
              <span className="socratic-title">🔥 Resolve Logical Conflict</span>
              <p className="socratic-text">
                These claims present logically incompatible conclusions. Let's inspect the underlying premises to help you rewrite this.
              </p>
              <button className="socratic-btn" onClick={() => alert("Interactive Coaching coming on Day 5!")}>
                Start Socratic Coaching
              </button>
            </div>
          </div>
        ) : (
          <div className="details-empty-state">
            <span className="details-empty-icon">👈</span>
            <div className="details-empty-text">
              Click any <strong>Claim Node</strong> or <strong>Conflict Relationship</strong> to inspect logical premises and Socratic questions.
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default App;
