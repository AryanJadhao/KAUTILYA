import uuid
import logging
import requests
from typing import List,Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
#from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import load_dotenv
load_dotenv()

from agent import build_graph
from config import settings
from schemas import (
    RunRequest,
    RunResponse,
    DeltaResult,
    HITLResumeRequest,
    HITLResumeResponse,
)
from database import (
    get_qdrant_client, ensure_collection, save_snapshot,
    save_monitored_urls, get_monitored_urls,
    save_pending_review, get_pending_reviews, update_pending_review,
    ensure_app_config_collection
)
# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINTER — shared across requests for HITL persistence
# ─────────────────────────────────────────────────────────────────────────────
from langgraph.checkpoint.memory import MemorySaver

# Global — lives for entire server lifetime
memory = MemorySaver()
graph = build_graph(checkpointer=memory)


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    ensure_app_config_collection(qdrant)
    logger.info("Qdrant collections ready.")
    yield
    # ── Shutdown ──
    logger.info("Shutting down.")


# ─────────────────────────────────────────────────────────────────────────────
# APP INIT
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Kautilya",
    description="Autonomous Competitive Intelligence powered by LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/ui")
async def serve_ui():
    return FileResponse("frontend/index.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── POST /store-webhook ───────────────────────────────────────────────────────
@app.post("/store-webhook")
async def store_webhook(data: dict):
    qdrant = get_qdrant_client()
    thread_id = data.get("thread_id")
    review = {
        "thread_id":  thread_id,
        "resume_url": data.get("resume_url"),
        "deltas":     data.get("deltas", []),
        "status":     "pending",
    }
    save_pending_review(qdrant, review)
    logger.info(f"[store-webhook] Stored pending review: {thread_id}")
    return {"status": "stored", "thread_id": thread_id}


# ── GET /pending ──────────────────────────────────────────────────────────────
@app.get("/pending")
async def get_pending():
    qdrant = get_qdrant_client()
    return {"pending_reviews": get_pending_reviews(qdrant)}


# ── POST /complete-review ─────────────────────────────────────────────────────
qdrant = get_qdrant_client()

@app.post("/complete-review")
async def complete_review(data: dict):
    """
    UI calls this after human approves/rejects.
    1. Calls /resume on LangGraph
    2. Marks review as completed in pending store
    """
    thread_id  = data.get("thread_id")
    approved   = data.get("approved", False)
    resume_url = data.get("resume_url")

    # Step 1 — Resume LangGraph
    config = _get_thread_config(thread_id)
    graph.update_state(config, {"approved": approved})
    graph.invoke(None, config=config)

    # Step 2 — Update review status in Qdrant
    update_pending_review(qdrant, thread_id, "completed", approved)

    # Step 3 — Call n8n Wait webhook to resume n8n flow
    if resume_url and approved:
        try:
            requests.get(resume_url, timeout=10)
            logger.info(f"[complete-review] n8n webhook called for thread: {thread_id}")
        except Exception as e:
            logger.error(f"[complete-review] n8n webhook error: {e}")

    return {
        "status":   "actions_executed" if approved else "rejected",
        "approved": approved,
        "thread_id": thread_id,
    }


@app.post("/urls")
async def save_urls(data: dict):
    qdrant = get_qdrant_client()
    urls = data.get("urls", [])
    save_monitored_urls(qdrant, urls)
    return {"status": "saved", "urls": urls}

@app.get("/urls")
async def get_urls():
    qdrant = get_qdrant_client()
    return {"urls": get_monitored_urls(qdrant)}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _parse_deltas(raw_deltas: list[dict]) -> list[DeltaResult]:
    return [
        DeltaResult(
            url=d["url"],
            analysis=d["analysis"],
            confidence=d.get("confidence", "low"),
        )
        for d in raw_deltas
    ]


def _get_thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "env": settings.APP_ENV}


# ── POST /run ─────────────────────────────────────────────────────────────────
@app.post("/run", response_model=RunResponse)
async def run_agent(request: RunRequest):
    """
    Start a new monitoring run.
    - Graph runs until it hits a delta or completes cleanly.
    - If deltas are found, graph PAUSES before the HITL node.
    - Returns thread_id so the client can call /resume later.
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    urls      = [str(u) for u in request.urls]

    logger.info(f"[run] thread_id={thread_id} | urls={urls}")

    initial_state = {
        "urls":               urls,
        "current_content":    {},
        "historical_content": {},
        "deltas":             [],
        "approved":           False,
    }

    try:
        final_state = graph.invoke(
            initial_state,
            config=_get_thread_config(thread_id),
        )

    except Exception as e:
        logger.error(f"[run] Graph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    deltas = final_state.get("deltas", [])

    # Graph paused before HITL — deltas found, waiting for human
    if deltas:
        return RunResponse(
            thread_id=thread_id,
            status="paused_for_review",
            deltas=_parse_deltas(deltas),
            message=f"{len(deltas)} strategic change(s) detected. Call /resume to approve or reject.",
        )

    # Graph completed — no changes found
    return RunResponse(
        thread_id=thread_id,
        status="no_changes",
        deltas=[],
        message="No significant changes detected across all URLs.",
    )


# ── POST /resume ──────────────────────────────────────────────────────────────
@app.post("/resume", response_model=HITLResumeResponse)
async def resume_agent(request: HITLResumeRequest):
    logger.info(f"[resume] thread_id={request.thread_id} | approved={request.approved}")

    config = _get_thread_config(request.thread_id)

    try:
        # Step 1 — update the approved flag in the checkpointed state
        graph.update_state(
            config,
            {"approved": request.approved},
        )

        # Step 2 — resume from where it paused (pass None, not a new state)
        final_state = graph.invoke(None, config=config)

    except Exception as e:
        logger.error(f"[resume] Graph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if request.approved:
        return HITLResumeResponse(
            thread_id=request.thread_id,
            status="actions_executed",
            message="Approved. Actions triggered for all detected changes.",
            deltas=_parse_deltas(final_state.get("deltas", []))
        )

    return HITLResumeResponse(
        thread_id=request.thread_id,
        status="run_rejected",
        message="Rejected. No actions taken.",
    )


# ── GET /status/{thread_id} ───────────────────────────────────────────────────
@app.get("/status/{thread_id}")
async def get_status(thread_id: str):
    """
    Inspect the current state of any run by thread_id.
    Useful for polling from a frontend or scheduler.
    """
    try:
        state = graph.get_state(config=_get_thread_config(thread_id))

    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread not found: {e}")

    if not state:
        raise HTTPException(status_code=404, detail="Thread not found.")

    next_nodes = state.next         # empty list = graph completed
    values     = state.values

    return {
        "thread_id":   thread_id,
        "status":      "paused" if next_nodes else "completed",
        "next_node":   next_nodes[0] if next_nodes else None,
        "deltas_found": len(values.get("deltas", [])),
        "approved":    values.get("approved", False),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)