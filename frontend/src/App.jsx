import React, { useCallback, useRef, useState, useEffect } from 'react';
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
    selectedIssue,
    isProcessing,
    uploadStatus,
    uploadProgress,
    uploadProgressMessage,
    error,
    fetchDocuments,
    selectDocument,
    uploadDocument,
    setSelectedNode,
    setSelectedEdge,
    clearSelection,
    coachingChat,
    isCoachingLoading,
    sendCoachingMessage,
    clearCoachingChat,
    versions,
    diffs,
    issues,
    uploadRevision,
  } = useArgusStore();

  const fileInputRef = useRef(null);
  const revisionInputRef = useRef(null);
  
  // Graph Filters state
  const [statusFilter, setStatusFilter] = useState('all');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [revisionTab, setRevisionTab] = useState('history');

  // Socratic Coaching active states & scroll references
  const [activeTab, setActiveTab] = useState('details');
  const [chatInput, setChatInput] = useState('');
  const chatEndRef = useRef(null);

  // Auto-scroll chat console when new messages arrive
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [coachingChat]);

  // Reset tab to Details when node or edge selection changes
  useEffect(() => {
    setActiveTab('details');
  }, [selectedNode, selectedEdge]);


  // Load documents list from backend on mount for persistence across reloads
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

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

  const handleRevisionClick = () => {
    if (revisionInputRef.current) {
      revisionInputRef.current.click();
    }
  };

  const handleRevisionChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadRevision(file);
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

  // --- Graph Dimming & Highlighting Logic (Day 4G) ---
  const hasSelection = !!selectedNode || !!selectedEdge;

  // Process nodes: Filter by status, then apply dimming if there is an active selection
  const processedNodes = graphData.nodes
    .filter((node) => {
      if (statusFilter === 'supported') return node.data?.status === 'supported';
      if (statusFilter === 'unsubstantiated') return node.data?.status === 'unsubstantiated';
      return true;
    })
    .map((node) => {
      let isDimmed = false;
      if (hasSelection) {
        if (selectedNode) {
          // Highlight ONLY the selected claim node
          isDimmed = selectedNode.id !== node.id;
        } else if (selectedEdge) {
          // Highlight BOTH claims involved in the selected conflict edge
          isDimmed = selectedEdge.source !== node.id && selectedEdge.target !== node.id;
        }
      }
      return {
        ...node,
        selected: selectedNode?.id === node.id,
        style: {
          ...node.style,
          opacity: isDimmed ? 0.25 : 1.0,
          pointerEvents: isDimmed ? 'none' : 'auto',
          transition: 'opacity 0.2s ease',
        },
      };
    });

  // Process edges: Filter by severity, then apply dimming if there is an active selection
  const processedEdges = graphData.edges
    .filter((edge) => {
      if (severityFilter === 'all') return true;
      return edge.data?.severity === severityFilter;
    })
    .map((edge) => {
      let isDimmed = false;
      if (hasSelection) {
        if (selectedEdge) {
          // Highlight ONLY the selected conflict edge
          isDimmed = selectedEdge.id !== edge.id;
        } else if (selectedNode) {
          // Highlight edges that are directly connected to the selected claim node
          isDimmed = edge.source !== selectedNode.id && edge.target !== selectedNode.id;
        }
      }
      return {
        ...edge,
        style: {
          ...edge.style,
          opacity: isDimmed ? 0.15 : 1.0,
          transition: 'opacity 0.2s ease',
        },
      };
    });

  return (
    <div className="app-container">
      {/* 1. Header */}
      <header className="app-header">
        <div className="logo-container">
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

        {/* Graph Filters Section (Day 4G) */}
        {selectedDocumentId && (
          <div className="sidebar-section">
            <h3 className="sidebar-section-title">Graph Filters</h3>
            <div className="filter-group">
              <label className="filter-label">Claims Filter</label>
              <select 
                value={statusFilter} 
                onChange={(e) => setStatusFilter(e.target.value)}
                className="filter-select"
              >
                <option value="all">All Claims</option>
                <option value="supported">✓ Supported Only</option>
                <option value="unsubstantiated">⚠ Needs Evidence Only</option>
              </select>
            </div>
            <div className="filter-group" style={{ marginTop: '12px' }}>
              <label className="filter-label">Severity Filter</label>
              <select 
                value={severityFilter} 
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="filter-select"
              >
                <option value="all">All Severities</option>
                <option value="high">High Severity Only</option>
                <option value="medium">Medium Severity Only</option>
                <option value="low">Low Severity Only</option>
              </select>
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
            <div className="loading-status" style={{ marginBottom: '8px' }}>
              {uploadProgressMessage || uploadStatus || 'Processing argument network...'}
            </div>
            
            {/* Progress Bar Container */}
            <div 
              style={{
                width: '100%',
                maxWidth: '360px',
                background: '#27272a',
                borderRadius: '9999px',
                height: '8px',
                overflow: 'hidden',
                margin: '12px 0 6px 0',
                border: '1px solid rgba(255,255,255,0.05)'
              }}
            >
              <div 
                style={{
                  width: `${Math.max(2, uploadProgress)}%`,
                  background: 'linear-gradient(90deg, #6366f1 0%, #a855f7 100%)',
                  height: '100%',
                  borderRadius: '9999px',
                  transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
                }}
              ></div>
            </div>
            
            <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#a1a1aa', marginBottom: '8px' }}>
              {Math.round(uploadProgress)}% Complete
            </div>

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
            nodes={processedNodes}
            edges={processedEdges}
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

      {/* 4. Details & Coaching Pane */}
      <section className="app-details">
        {selectedDocumentId && (
          <div className="details-tabs revision-tabs">
            <button
              className={`tab-btn ${revisionTab === 'history' ? 'active' : ''}`}
              onClick={() => { clearSelection(); setRevisionTab('history'); }}
            >
              📑 Drafts ({versions.length})
            </button>
            <button
              className={`tab-btn ${revisionTab === 'issues' ? 'active' : ''}`}
              onClick={() => { clearSelection(); setRevisionTab('issues'); }}
            >
              📋 Issues ({issues.length})
            </button>
            <button
              className={`tab-btn ${revisionTab === 'diffs' ? 'active' : ''}`}
              onClick={() => { clearSelection(); setRevisionTab('diffs'); }}
            >
              ⚡ Diff ({diffs.length})
            </button>
          </div>
        )}
        {selectedNode || selectedEdge || selectedIssue ? (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Tab Navigation */}
            <div className="details-tabs">
              <button
                className={`tab-btn ${activeTab === 'details' ? 'active' : ''}`}
                onClick={() => setActiveTab('details')}
              >
                🔍 Analysis
              </button>
              <button
                className={`tab-btn ${activeTab === 'coaching' ? 'active' : ''}`}
                onClick={() => setActiveTab('coaching')}
              >
                💡 Socratic
              </button>
            </div>

            {/* Tab Content */}
            {activeTab === 'details' ? (
              selectedNode ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1 }}>
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
                    <button className="socratic-btn" onClick={() => setActiveTab('coaching')}>
                      Trigger Socratic Team
                    </button>
                  </div>
                </div>
              ) : selectedEdge ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1 }}>
                  <div className="details-header">
                    <span className="details-location" style={{ color: 'var(--color-danger)' }}>
                      CONTRADICTION &bull; SEVERITY: {selectedEdge.data?.severity?.toUpperCase() || 'HIGH'}
                    </span>
                    <h2 className="details-title">Argument Conflict</h2>
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
                    <button className="socratic-btn" onClick={() => setActiveTab('coaching')}>
                      Start Socratic Coaching
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1 }}>
                  <div className="details-header">
                    <span className="details-location">TRACKED ISSUE</span>
                    <h2 className="details-title">{selectedIssue.issue_type.toUpperCase()} Issue</h2>
                  </div>
                  <div className="details-section">
                    <span className="details-section-title">Status</span>
                    <div className="details-text-box">{selectedIssue.status.toUpperCase()}</div>
                  </div>
                  <div className="details-section">
                    <span className="details-section-title">Coaching question</span>
                    <div className="details-text-box">{selectedIssue.question_text}</div>
                  </div>
                  <button className="socratic-btn" onClick={() => setActiveTab('coaching')}>
                    Coach me on this issue
                  </button>
                </div>
              )
            ) : (
              /* Coaching Chat Pane */
              <div className="chat-panel">
                <div className="chat-messages">
                  {coachingChat.map((msg, idx) => (
                    <div
                      key={idx}
                      className={`chat-message ${msg.sender} ${msg.status}`}
                    >
                      {/* Simple custom markdown parsing */}
                      {msg.text.split('\n').map((line, lIdx) => {
                        if (line.startsWith('### ')) {
                          return (
                            <h3 key={lIdx} style={{ margin: '12px 0 6px 0', fontSize: '14px', fontWeight: '700', color: msg.status === 'intercepted' ? '#f87171' : '#fca5a5' }}>
                              {line.replace('### ', '')}
                            </h3>
                          );
                        }
                        if (line.startsWith('**') && line.endsWith('**')) {
                          return (
                            <strong key={lIdx} style={{ display: 'block', margin: '8px 0 4px 0', fontSize: '13px', color: '#f3f4f6' }}>
                              {line.replace(/\*\*/g, '')}
                            </strong>
                          );
                        }
                        if (line.startsWith('- ') || line.startsWith('* ')) {
                          return (
                            <li key={lIdx} style={{ marginLeft: '12px', fontSize: '12px', listStyleType: 'disc', color: '#e5e7eb', marginBottom: '4px' }}>
                              {line.substring(2)}
                            </li>
                          );
                        }
                        return (
                          <p key={lIdx} style={{ margin: '6px 0', fontSize: '13px', color: '#d1d5db', lineHeight: '1.5' }}>
                            {line}
                          </p>
                        );
                      })}

                      {/* Render Interactive Matrix options if intercepted */}
                      {msg.status === 'intercepted' && (
                        <div style={{ marginTop: '16px' }}>
                          <span className="matrix-options-title">💡 Socratic Redirect Matrix</span>
                          <button
                            className="matrix-pill"
                            onClick={() => sendCoachingMessage("Give me a structural outline for this section.")}
                          >
                            📝 Structural Outline Guide
                          </button>
                          <button
                            className="matrix-pill"
                            onClick={() => sendCoachingMessage("What core assumptions or premises behind this claim should I verify?")}
                          >
                            ⚖️ Verify Logical Premises
                          </button>
                          <button
                            className="matrix-pill"
                            onClick={() => sendCoachingMessage("What empirical data or citations do I need to support this logic?")}
                          >
                            🔎 Identify Evidentiary Needs
                          </button>
                          <button
                            className="matrix-pill"
                            onClick={() => sendCoachingMessage("What potential counterarguments or conflicts could arise from this reasoning?")}
                          >
                            🔥 Discover Logical Conflicts
                          </button>
                        </div>
                      )}
                    </div>
                  ))}

                  {isCoachingLoading && (
                    <div className="chat-message argus loading-bubble">
                      🔮 Socratic Specialists analyzing logic, citations & assumptions...
                    </div>
                  )}

                  <div ref={chatEndRef} />
                </div>

                {/* Input Area */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (chatInput.trim() && !isCoachingLoading) {
                      sendCoachingMessage(chatInput);
                      setChatInput('');
                    }
                  }}
                  className="chat-input-container"
                >
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder={
                      selectedNode
                        ? "Ask about this claim's assumptions or empirical gaps..."
                        : "Ask how to resolve this contradiction..."
                    }
                    className="chat-input"
                    disabled={isCoachingLoading}
                  />
                  <button
                    type="submit"
                    className="socratic-btn"
                    style={{ borderRadius: '4px', padding: '0 16px' }}
                    disabled={isCoachingLoading}
                  >
                    Send
                  </button>
                </form>
              </div>
            )}
          </div>
        ) : selectedDocumentId ? (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* Sub-tab content */}
            {revisionTab === 'history' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1, padding: '16px' }}>
                <div className="details-header">
                  <span className="details-location">Draft Session Sequence</span>
                  <h2 className="details-title">Revision History</h2>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {versions.length === 0 ? (
                    <div className="details-text-box" style={{ color: 'var(--text-muted)', borderStyle: 'dashed', textAlign: 'center' }}>
                      Gathering draft records...
                    </div>
                  ) : (
                    versions.map((ver) => (
                      <div key={ver.version_id} className="details-text-box" style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <strong>Draft V{ver.version_number}</strong>
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {new Date(ver.created_at).toLocaleTimeString()}
                          </span>
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>ID: {ver.version_id.substring(0, 8)}...</div>
                        {ver.parent_version_id && (
                          <div style={{ fontSize: '12px', color: '#fbcfe8', marginTop: '4px' }}>
                            ← Parent draft ID: {ver.parent_version_id.substring(0, 8)}...
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>

                <div className="socratic-coaching-box" style={{ marginTop: 'auto' }}>
                  <span className="socratic-title">📝 Upload Next Revision Draft</span>
                  <p className="socratic-text">
                    Argus compares your new draft copy with the current version, matches paragraph changes, aligns claim coordinates, and re-analyzes outstanding issues to detect resolution or escalation!
                  </p>
                  <button className="socratic-btn" onClick={handleRevisionClick}>
                    Upload Draft V{versions.length + 1}
                  </button>
                  <input
                    type="file"
                    ref={revisionInputRef}
                    onChange={handleRevisionChange}
                    accept=".pdf,.docx"
                    style={{ display: 'none' }}
                  />
                </div>
              </div>
            )}

            {revisionTab === 'issues' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1, padding: '16px' }}>
                <div className="details-header">
                  <span className="details-location">Tracked Socratic Issues</span>
                  <h2 className="details-title">Resolution History</h2>
                </div>
                {issues.length === 0 ? (
                  <div className="details-text-box" style={{ color: 'var(--text-muted)', borderStyle: 'dashed', textAlign: 'center' }}>
                    No Socratic issues flagged for this document yet. Start coaching on specific claims to register issues.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {issues.map((issue) => {
                      const statusColors = {
                        open: '#60a5fa',
                        addressed: '#34d399',
                        persistent: '#f59e0b',
                        escalated: '#ef4444',
                      };
                      return (
                        <div key={issue.id} className="details-text-box" style={{ borderLeft: `4px solid ${statusColors[issue.status] || '#9ca3af'}` }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                            <span style={{ fontSize: '11px', textTransform: 'uppercase', fontWeight: 'bold', color: statusColors[issue.status] }}>
                              {issue.status.toUpperCase()}
                            </span>
                            {issue.escalation_count > 0 && (
                              <span style={{ fontSize: '11px', color: '#ef4444', fontWeight: 'bold' }}>
                                ⚠️ Escalated x{issue.escalation_count}
                              </span>
                            )}
                          </div>
                          <strong>{issue.issue_type.toUpperCase()}: {issue.section}</strong>
                          <p style={{ fontSize: '12px', margin: '4px 0', color: '#d1d5db' }}>{issue.description}</p>
                          <div style={{ background: 'rgba(255,255,255,0.04)', padding: '6px', borderRadius: '4px', fontSize: '11px', marginTop: '6px', color: '#fca5a5' }}>
                            ❓ {issue.question_text}
                          </div>
                          <button
                            className="socratic-btn"
                            style={{ marginTop: '10px', width: '100%' }}
                            onClick={() => {
                              useArgusStore.getState().setSelectedIssue(issue);
                              setActiveTab('coaching');
                            }}
                          >
                            Coach me on this issue
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {revisionTab === 'diffs' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', overflowY: 'auto', flex: 1, padding: '16px' }}>
                <div className="details-header">
                  <span className="details-location">Textual Differences</span>
                  <h2 className="details-title">Paragraph Diff</h2>
                </div>
                {diffs.length === 0 ? (
                  <div className="details-text-box" style={{ color: 'var(--text-muted)', borderStyle: 'dashed', textAlign: 'center' }}>
                    This is the initial draft (V1). Upload a revision (V2) to view paragraph changes.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {diffs.map((diff, idx) => {
                      const changeBg = {
                        added: 'rgba(16, 185, 129, 0.1)',
                        removed: 'rgba(239, 68, 68, 0.1)',
                        modified: 'rgba(245, 158, 11, 0.1)',
                        unchanged: 'transparent',
                      };
                      const changeBorder = {
                        added: '1px solid rgba(16, 185, 129, 0.25)',
                        removed: '1px solid rgba(239, 68, 68, 0.25)',
                        modified: '1px solid rgba(245, 158, 11, 0.25)',
                        unchanged: '1px solid var(--border-color)',
                      };
                      return (
                        <div key={idx} className="details-text-box" style={{ background: changeBg[diff.change_type], border: changeBorder[diff.change_type] }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '11px' }}>
                            <span style={{ fontWeight: 'bold', textTransform: 'uppercase' }}>{diff.change_type}</span>
                            <span>{diff.location}</span>
                          </div>
                          {diff.change_type === 'modified' ? (
                            <div>
                              <div style={{ color: '#ef4444', textDecoration: 'line-through', fontSize: '12px', marginBottom: '4px' }}>
                                - {diff.before}
                              </div>
                              <div style={{ color: '#10b981', fontSize: '12px' }}>
                                + {diff.after}
                              </div>
                              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                Similarity: {(diff.similarity * 100).toFixed(0)}%
                              </div>
                            </div>
                          ) : (
                            <div style={{ fontSize: '12px', color: diff.change_type === 'removed' ? '#fca5a5' : '#e5e7eb' }}>
                              {diff.after || diff.before}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
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
