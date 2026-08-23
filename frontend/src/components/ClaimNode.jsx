import React, { memo } from 'react';
import { Handle, Position } from 'reactflow';

const ClaimNode = ({ data, selected }) => {
  const isSupported = data.status === 'supported';
  const borderClass = isSupported ? 'node-supported' : 'node-unsubstantiated';
  const selectedClass = selected ? 'node-selected' : '';

  // Scale node size based on centrality
  const scaleStyle = {
    transform: `scale(${1 + (data.centrality || 0) * 0.25})`,
    transition: 'transform 0.2s ease',
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

        {data.open_questions && data.open_questions.length > 0 && data.conflict_count === 0 && (
          <span className="node-alert-icon" title={`${data.open_questions.length} open questions`}>
            ❓ {data.open_questions.length}
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
