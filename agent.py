from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from nodes.scraper import scrape_websites
from nodes.memory  import check_history
from nodes.delta   import analyze_deltas
from nodes.hitl    import human_review, execute_action
from schemas       import AgentState


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH DEFINITION
# ─────────────────────────────────────────────────────────────────────────────
def route_after_delta(state: AgentState) -> str:
    """Conditional edge: go to HITL if deltas found, else end."""
    if state.get("deltas"):
        return "hitl"
    print("  No significant changes found. Ending run.")
    return END


def build_graph(checkpointer=None):
    workflow = StateGraph(AgentState)

    workflow.add_node("scrape",  scrape_websites)
    workflow.add_node("history", check_history)
    workflow.add_node("compare", analyze_deltas)
    workflow.add_node("hitl",    human_review)
    workflow.add_node("action",  execute_action)

    workflow.set_entry_point("scrape")

    workflow.add_edge("scrape",  "history")
    workflow.add_edge("history", "compare")

    workflow.add_conditional_edges(
        "compare",
        route_after_delta,
        {
            "hitl": "hitl",
            END:    END,
        }
    )

    workflow.add_edge("hitl",   "action")
    workflow.add_edge("action", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl"],
    )