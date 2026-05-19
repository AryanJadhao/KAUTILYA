from typing import List, Dict, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, HttpUrl, Field


# ─────────────────────────────────────────────────────────────────────────────
# LANGGRAPH STATE
# ─────────────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    """
    The single source of truth passed between every LangGraph node.
    Each node receives this, modifies relevant fields, and returns the update.
    """
    urls:               List[str]           # URLs to monitor
    current_content:    Dict[str, str]      # {url: scraped_text} — filled by scrape node
    historical_content: Dict[str, Optional[str]]  # {url: past_text | None} — filled by history node
    deltas:             List[Dict]          # [{url, analysis, confidence}] — filled by delta node
    approved:           bool                # set by HITL resume call


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    """POST /run — start a new monitoring run."""
    urls: List[HttpUrl] = Field(
        ...,
        min_length=1,
        description="List of URLs to monitor for strategic changes.",
        examples=[["https://openai.com/pricing", "https://anthropic.com"]]
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Optional thread ID for resuming a paused run. Leave empty for new runs."
    )


class DeltaResult(BaseModel):
    """A single detected change."""
    url:        str
    analysis:   str
    confidence: str   # "high" | "low"


class RunResponse(BaseModel):
    """Response after invoking the graph."""
    thread_id:  str
    status:     str                  # "completed" | "paused_for_review" | "no_changes"
    deltas:     List[DeltaResult]   = []
    message:    str                  = ""


class HITLResumeRequest(BaseModel):
    """POST /resume — human approves or rejects the detected deltas."""
    thread_id:  str  = Field(..., description="Thread ID of the paused run.")
    approved:   bool = Field(..., description="True to trigger actions, False to discard.")


class HITLResumeResponse(BaseModel):
    """Response after resuming a paused run."""
    thread_id:  str
    status:     str   # "actions_executed" | "run_rejected"
    message:    str   = ""
    deltas:     List[DeltaResult] = []


# ─────────────────────────────────────────────────────────────────────────────
# QDRANT PAYLOAD SCHEMA  (not a Pydantic model — just a typed dict for clarity)
# ─────────────────────────────────────────────────────────────────────────────
class SnapshotPayload(TypedDict):
    """
    Shape of the payload stored in Qdrant for each URL snapshot.
    Used in database.py when saving and retrieving snapshots.
    """
    url:          str
    content:      str
    saved_at:     str   # ISO 8601 timestamp