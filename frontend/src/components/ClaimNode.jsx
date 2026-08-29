import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';

const ClaimNode = ({ data, selected }) => {
  const isSupported = data.status === 'supported';
  const borderClass = isSupported ? 'node-supported' : 'node-unsubstantiated';
  const selectedClass = selected ? 'node-selected' : '';

  // Scale node size based on centrality
  const scaleStyle = {
    transform: `scale(${(1 + (data.centrality || 0) * 0.25) * (selected ? 1.45 : 1)})`,
    transformOrigin: 'center center',
    transition: 'transform 0.2s ease, width 0.2s ease',
    position: 'relative',
    zIndex: selected ? 1000 : 1,
  };

  return (
    <div 
      className={`claim-node-container ${borderClass} ${selectedClass}`} 
      style={scaleStyle}
    >
      {/* Target handle at the top */}
      <Handle 
        type="target" 
        position={Position.Top} 
        style={{ background: '#ef4444', border: '1px solid #7f1d1d', width: '8px', height: '8px' }} 
      />
      
      <div className="node-header">
        <span className="node-location">{data.chapter || 'Section'} &bull; {data.section || 'General'}</span>
        <span className={`node-badge ${isSupported ? 'badge-supported' : 'badge-unsubstantiated'}`}>
          {isSupported ? '✓ Supported' : '⚠ Needs Evidence'}
        </span>
      </div>
      
      <div className="node-body">
        <p className="node-text">{data.text}</p>
      </div>

      <div className="node-footer">
        <span className="node-centrality">Centrality: {((data.centrality || 0) * 100).toFixed(0)}%</span>
        
        {data.conflict_count > 0 && (
          <span className="node-conflict-count" title={`${data.conflict_count} logical conflicts`}>
            🔴 {data.conflict_count} conflict{data.conflict_count > 1 ? 's' : ''}
          </span>
        )}

        {data.issue_status === 'escalated' && (
          <span className="node-issue-tag issue-tag-escalated" title={`Escalated issue (x${data.escalation_count || 1})`}>
            ⚠️ Escalated
          </span>
        )}
        {data.issue_status === 'persistent' && (
          <span className="node-issue-tag issue-tag-persistent" title="Persistent issue across drafts">
            ⏳ Persistent
          </span>
        )}
        {data.issue_status === 'open' && (
          <span className="node-issue-tag issue-tag-open" title="Open Socratic issue">
            ⚡ Open Issue
          </span>
        )}
        {data.issue_status === 'addressed' && (
          <span className="node-issue-tag issue-tag-addressed" title="Issue resolved in revision">
            ✓ Resolved
          </span>
        )}
      </div>

      {/* Source handle at the bottom */}
      <Handle 
        type="source" 
        position={Position.Bottom} 
        style={{ background: '#ef4444', border: '1px solid #7f1d1d', width: '8px', height: '8px' }} 
      />
    </div>
  );
};

export default memo(ClaimNode);
