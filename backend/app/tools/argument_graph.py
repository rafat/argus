import logging
import networkx as nx
from typing import List

from app.models.claim import Claim
from app.models.conflict import Conflict
from app.models.graph import ArgumentGraph, GraphNode, GraphNodeData, GraphEdge, GraphEdgeData

logger = logging.getLogger(__name__)


class ArgumentGraphBuilder:
    """
    Builds a canonical, analyzed ArgumentGraph from Firestore claims and conflicts.
    Separates the presentation layer (React Flow adapters) from raw Firestore entities.
    """

    def build(self, claims: List[Claim], conflicts: List[Conflict]) -> ArgumentGraph:
        if not claims:
            return ArgumentGraph(nodes=[], edges=[])

        valid_claim_ids = {claim.id for claim in claims}
        
        # 1. Initialize NetworkX analysis graph
        G = nx.DiGraph()
        
        # Add all valid claims as nodes
        for claim in claims:
            G.add_node(claim.id)

        # Track conflict involvements for metadata counts
        conflict_counts = {claim.id: 0 for claim in claims}

        # Filter out malformed conflicts to prevent crashing
        valid_conflicts = []
        for conflict in conflicts:
            if conflict.claim_a_id not in valid_claim_ids or conflict.claim_b_id not in valid_claim_ids:
                logger.warning(
                    f"Skipping malformed conflict '{conflict.id}': references non-existent "
                    f"claim_a_id '{conflict.claim_a_id}' or claim_b_id '{conflict.claim_b_id}'"
                )
                continue
            
            valid_conflicts.append(conflict)
            G.add_edge(conflict.claim_a_id, conflict.claim_b_id)
            
            # Increment conflict counts for the involved claims
            conflict_counts[conflict.claim_a_id] += 1
            conflict_counts[conflict.claim_b_id] += 1

        # 2. Compute degree centrality (using undirected equivalent or directed degree)
        # Degree centrality is computed as the fraction of nodes connected to it.
        if len(claims) > 1:
            centrality_scores = nx.degree_centrality(G)
        else:
            centrality_scores = {claims[0].id: 1.0}

        # 3. Compute organic layout coordinates using spring layout
        if len(claims) > 1:
            # spring_layout behaves robustly even on disconnected components
            pos = nx.spring_layout(G, k=1.5, seed=42)
        else:
            pos = {claims[0].id: [0.0, 0.0]}

        # 4. Construct GraphNode list
        nodes = []
        for claim in claims:
            node_id = claim.id
            coords = pos[node_id]
            
            node_data = GraphNodeData(
                text=claim.text,
                chapter=claim.chapter or "",
                section=claim.section or "",
                status=claim.status or "unsubstantiated",
                confidence=claim.confidence if claim.confidence is not None else 1.0,
                centrality=float(centrality_scores.get(node_id, 0.0)),
                conflict_count=conflict_counts.get(node_id, 0),
                open_questions=claim.open_questions or [],
                evidence_cited=claim.evidence_cited or []
            )
            
            nodes.append(
                GraphNode(
                    id=node_id,
                    type="claimNode",
                    position={"x": float(coords[0] * 600), "y": float(coords[1] * 600)},
                    data=node_data
                )
            )

        # 5. Construct GraphEdge list
        edges = []
        for conflict in valid_conflicts:
            edge_data = GraphEdgeData(
                explanation=conflict.explanation,
                severity=conflict.severity or "high",
                confidence=conflict.confidence if conflict.confidence is not None else 1.0
            )
            
            edges.append(
                GraphEdge(
                    id=conflict.id,
                    source=conflict.claim_a_id,
                    target=conflict.claim_b_id,
                    type="conflictEdge",
                    animated=(conflict.severity == "high"),
                    data=edge_data
                )
            )

        return ArgumentGraph(nodes=nodes, edges=edges)
