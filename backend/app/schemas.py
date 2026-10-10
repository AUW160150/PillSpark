from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field as PField

FIELD_STATUSES = ("verified", "needs_review", "unreadable", "missing", "resolved")
ORDER_STATUSES = ("queued", "processing", "blocked", "ready", "error")


class Candidate(BaseModel):
    value: Any = None
    votes: int = 0
    sources: List[str] = PField(default_factory=list)


class FieldResult(BaseModel):
    name: str
    value: Optional[Any] = None            # withheld (None) when unreadable/missing — never a guess
    confidence: float = 0.0
    status: str = "missing"                # one of FIELD_STATUSES
    reasons: List[str] = PField(default_factory=list)
    candidates: List[Candidate] = PField(default_factory=list)
    evidence: Dict[str, Any] = PField(default_factory=dict)
    self_confidence: Optional[float] = None
    agreement: Optional[float] = None
    registry_score: Optional[float] = None
    pharmacist_question: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_note: Optional[str] = None


class Order(BaseModel):
    order_id: str
    source_image: str
    created_at: float
    status: str = "queued"                 # one of ORDER_STATUSES
    stage: str = "Queued"
    progress: int = 0
    llm_mode: str = "mock"
    models: List[str] = PField(default_factory=list)
    fields: Dict[str, FieldResult] = PField(default_factory=dict)
    review_queue: List[str] = PField(default_factory=list)
    events: List[Dict[str, Any]] = PField(default_factory=list)
    metrics: Dict[str, Any] = PField(default_factory=dict)
    prism: Dict[str, Any] = PField(default_factory=dict)
    raw_passes: List[Dict[str, Any]] = PField(default_factory=list)
    error: Optional[str] = None
    completed_at: Optional[float] = None
