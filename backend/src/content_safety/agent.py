import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from content_safety.config import settings
from content_safety.state import ModerationState
from content_safety.tools import TOOLS


AGENT_SYSTEM_PROMPT = """你是内容安全审核 Agent。

你必须按以下方式工作：
1. 先判断内容可能涉及哪些安全类别。
2. 如果需要政策、垃圾信号或上下文线索，调用工具。
3. 工具结果不足时，可以继续调用工具。
4. 当证据足够时，输出最终 JSON，不要输出多余解释。

最终 JSON 格式：
{
  "decision": "approved/rejected/needs_review",
  "reason": "简短原因",
  "confidence": 0.0,
  "evidence": ["证据1", "证据2"]
}

决策要求：
- 明显违规且证据充分：rejected
- 正常讨论、教育、新闻或低风险内容：approved
- 高风险、语义不确定、政策冲突、置信度低于 0.75：needs_review
"""


def build_llm():
    llm = ChatOllama(model=settings.model, temperature=0)
    return llm.bind_tools(TOOLS)


def enter_agent(state: ModerationState) -> dict:
    content = state["content"]
    rule_hits = ", ".join(state.get("rule_hits", [])) or "无"
    workflow_reason = state.get("workflow_reason", "无")

    return {
        "messages": [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"请审核以下内容：\n{content}\n\n"
                    f"场景：{state.get('scene', 'default')}\n"
                    f"Workflow 初筛原因：{workflow_reason}\n"
                    f"规则命中：{rule_hits}"
                )
            ),
        ]
    }


def agent_assistant(state: ModerationState) -> dict:
    try:
        response = build_llm().invoke(state["messages"])
    except Exception as exc:
        response = AIMessage(
            content=json.dumps(
                {
                    "decision": "needs_review",
                    "reason": f"Agent 调用失败，转人工审核：{type(exc).__name__}",
                    "confidence": 0.0,
                    "evidence": [str(exc)[:300]],
                },
                ensure_ascii=False,
            )
        )
    return {"messages": [response]}


def parse_agent_decision(state: ModerationState) -> dict:
    last_message = state["messages"][-1]
    raw = last_message.content if isinstance(last_message.content, str) else str(last_message.content)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "agent_decision": "needs_review",
            "agent_reason": "Agent 输出不是合法 JSON，需要人工审核",
            "confidence": 0.0,
            "evidence": [raw[:500]],
        }

    decision = data.get("decision", "needs_review")
    if decision not in ["approved", "rejected", "needs_review"]:
        decision = "needs_review"

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    evidence = data.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = [str(evidence)]

    return {
        "agent_decision": decision,
        "agent_reason": str(data.get("reason", "无原因")),
        "confidence": confidence,
        "evidence": [str(item) for item in evidence],
    }


def route_after_agent(state: ModerationState) -> Literal["human_review", "finalize_agent"]:
    if state.get("agent_decision") == "needs_review":
        return "human_review"
    if state.get("confidence", 0.0) < 0.75:
        return "human_review"
    return "finalize_agent"


def finalize_agent(state: ModerationState) -> dict:
    return {
        "final_decision": state["agent_decision"],
        "final_reason": state["agent_reason"],
    }

