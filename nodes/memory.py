from schemas import AgentState
from database import get_qdrant_client, ensure_collection, get_snapshot


def check_history(state: AgentState) -> AgentState:
    """Fetch last known snapshot for each URL from Qdrant."""
    print("--- NODE: check_history ---")
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    history = {}

    for url in state["urls"]:
        snapshot = get_snapshot(qdrant, url)
        history[url] = snapshot   # None if first run
        if snapshot is None:
            print(f"  [memory] No history found for: {url} (first run)")
        else:
            print(f"  [memory] History loaded for: {url}")

    return {"historical_content": history}