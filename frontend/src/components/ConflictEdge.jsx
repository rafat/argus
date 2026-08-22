import React from 'react';
import { getBezierPath } from 'reactflow';

export default function ConflictEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
  selected,
}) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const isHighSeverity = data?.severity === 'high';
  const strokeColor = selected ? '#fca5a5' : '#dc2626'; // Highlighted crimson when selected
  
  const edgeStyle = {
    ...style,
    stroke: strokeColor,
    strokeWidth: isHighSeverity ? 3 : 2,
    strokeDasharray: isHighSeverity ? '5,5' : undefined,
    animation: isHighSeverity ? 'dash 1.5s linear infinite' : undefined,
  };

  return (
    <path
      id={id}
      style={edgeStyle}
      className={`react-flow__edge-path conflict-edge ${isHighSeverity ? 'animated-edge' : ''}`}
      d={edgePath}
      markerEnd={markerEnd}
    />
  );
}
