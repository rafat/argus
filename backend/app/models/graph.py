from pydantic import BaseModel, Field


class GraphNodeData(BaseModel):
    text: str
    chapter: str = ""
    section: str = ""
    status: str
    confidence: float
    centrality: float = 0.0
    conflict_count: int = 0
    open_questions: list[str] = Field(default_factory=list)
    evidence_cited: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    type: str = "claimNode"
    position: dict[str, float]
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    explanation: str
    severity: str
    confidence: float


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "conflictEdge"
    animated: bool = False
    data: GraphEdgeData


class ArgumentGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
