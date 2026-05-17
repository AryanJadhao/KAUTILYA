import requests
from schemas import AgentState
from config import settings


def human_review(state: AgentState) -> AgentState:
    """
    Graph pauses BEFORE this node via interrupt_before=["hitl"].
    LangGraph freezes state here and waits for /resume to be called.
    """
    print("--- NODE: human_review (PAUSED — awaiting human decision) ---")
    return {}


def execute_action(state: AgentState) -> AgentState:
    print("--- NODE: execute_action ---")

    if not state.get("approved", False):
        print("  [action] Rejected by reviewer. No action taken.")
        return {}

    # Slack notification now handled by n8n
    # Just log the action here
    for delta in state.get("deltas", []):
        print(f"  [action] Change processed for: {delta['url']}")

    return {}


def _send_slack_alert(delta: dict) -> None:
    """Send a formatted Slack message for a single delta."""

    confidence_emoji = "🔴" if delta.get("confidence") == "high" else "🟡"

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 IntelliEdge — Strategic Change Detected",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*URL:*\n<{delta['url']}|{delta['url']}>"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n{confidence_emoji} {delta.get('confidence', 'low').upper()}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Analysis:*\n{delta['analysis']}"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "✅ Approved by human reviewer via IntelliEdge HITL"
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(
            settings.SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"  [slack] Alert sent for: {delta['url']}")
        else:
            print(f"  [slack] Failed — status {response.status_code}: {response.text}")

    except Exception as e:
        print(f"  [slack] Error sending alert: {e}")