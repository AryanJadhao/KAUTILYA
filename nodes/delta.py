from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from schemas import AgentState
from database import get_qdrant_client, save_snapshot
from config import settings


llm = ChatOpenAI(
    model=settings.LLM_MODEL,
    temperature=settings.LLM_TEMPERATURE,
    openai_api_key=settings.OPENAI_API_KEY,
)


def analyze_deltas(state: AgentState) -> AgentState:
    """LLM compares current vs historical content and extracts strategic deltas."""
    print("--- NODE: analyze_deltas ---")
    qdrant = get_qdrant_client()
    found_deltas = []

    for url, current in state["current_content"].items():
        past = state["historical_content"].get(url)

        # First run — no history yet, save and skip comparison
        if past is None:
            save_snapshot(qdrant, url, current)
            print(f"  [delta] First run snapshot saved for: {url}")
            continue

        prompt = f"""You are a competitive intelligence analyst.

Compare the CURRENT version of a webpage against its PAST version.
Identify only STRATEGIC changes such as:
- Pricing changes
- New or removed product features
- Changes in mission, positioning, or messaging
- Leadership or team changes
- New partnerships or integrations

Ignore: formatting, timestamps, cookie banners, navigation tweaks.

URL: {url}

PAST VERSION:
{past[:2000]}

CURRENT VERSION:
{current[:2000]}

If you find strategic changes, describe them clearly and concisely.
If there are no strategic changes, respond with exactly: NO_SIGNIFICANT_CHANGE
"""
        response = llm.invoke([HumanMessage(content=prompt)])
        analysis = response.content.strip()

        # TEMP: force a fake delta for HITL testing
        #analysis = "OpenAI has reduced GPT-4o pricing by 50% from $5.00 to $2.50 per 1M tokens."

        if analysis != "NO_SIGNIFICANT_CHANGE":
            found_deltas.append({
                "url":        url,
                "analysis":   analysis,
                "confidence": "high" if len(analysis) > 200 else "low",
            })
            print(f"  [delta] Change detected at: {url}")
        else:
            print(f"  [delta] No change at: {url}")

        # Always update snapshot with latest content
        save_snapshot(qdrant, url, current)

    return {"deltas": found_deltas}