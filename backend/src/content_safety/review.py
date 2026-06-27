from langgraph.types import interrupt

from content_safety.state import ModerationState


def human_review(state: ModerationState) -> dict:
    human_result = interrupt(
        {
            "question": "请人工审核该内容，并给出 approved / rejected / needs_review。",
            "content": state["content"],
            "workflow_reason": state.get("workflow_reason"),
            "rule_hits": state.get("rule_hits", []),
            "agent_decision": state.get("agent_decision"),
            "agent_reason": state.get("agent_reason"),
            "confidence": state.get("confidence"),
            "evidence": state.get("evidence", []),
        }
    )

    if isinstance(human_result, str):
        return {
            "human_decision": "needs_review",
            "human_reason": human_result,
        }

    decision = human_result.get("decision", "needs_review")
    if decision not in ["approved", "rejected", "needs_review"]:
        decision = "needs_review"

    return {
        "human_decision": decision,
        "human_reason": human_result.get("reason", "人工审核未提供原因"),
    }


def finalize_human(state: ModerationState) -> dict:
    return {
        "final_decision": state["human_decision"],
        "final_reason": state["human_reason"],
    }

