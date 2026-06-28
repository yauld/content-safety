import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from content_safety.config import settings
from content_safety.state import ModerationState
from content_safety.tools import TOOLS


# Agent 的系统提示词负责约束模型的审核步骤和最终输出格式。
# 强制输出结构化 JSON，便于 parse_agent_decision 将模型结果写回 LangGraph State。
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
    """创建审核模型，并绑定 Agent 在推理过程中可以调用的内容安全工具。"""
    # temperature=0 降低输出随机性，让相同内容的审核结果尽量稳定。
    llm = ChatOllama(model=settings.model, temperature=0)

    # bind_tools 会把工具定义提供给模型；模型只负责产生 tool_calls，
    # 实际工具执行由 graph.py 中注册的 ToolNode 完成。
    return llm.bind_tools(TOOLS)


def enter_agent(state: ModerationState) -> dict:
    """把 Workflow 初筛结果整理成 Agent 的首轮对话上下文。

    该节点本身不调用模型，只负责创建 SystemMessage 和 HumanMessage。
    下一节点 agent_assistant 会使用这里生成的 messages 发起模型调用。
    """
    content = state["content"]
    rule_hits = ", ".join(state.get("rule_hits", [])) or "无"
    workflow_reason = state.get("workflow_reason", "无")

    return {
        # ModerationState.messages 使用 add_messages reducer，因此这里返回的消息
        # 会追加到状态中，而不是覆盖已有的消息历史。
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
    """调用模型完成一轮推理，并把模型响应追加到消息历史。

    模型可能返回两种响应：
    - 带 tool_calls 的 AIMessage：图会转到 tools 节点执行工具；
    - 不带 tool_calls 的 AIMessage：图会转到 parse_agent_decision 解析最终 JSON。
    """
    messages = state.get("messages")
    if not messages:
        raise RuntimeError("messages 缺失，请确认已先执行 enter_agent。")

    try:
        response = build_llm().invoke(messages)
    except Exception as exc:
        # 模型服务不可用时不让整个审核请求直接失败，而是构造一个低置信度结果，
        # 交由后续路由进入人工审核。异常文本会被截断，避免 State 过度膨胀。
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

    # 只返回本轮新增消息，由 messages reducer 合并进完整对话历史。
    return {"messages": [response]}


def parse_agent_decision(state: ModerationState) -> dict:
    """解析模型最后一条消息，并规范化为 Agent 阶段的审核字段。"""
    # 只有模型不再请求工具时才会进入此节点，因此最后一条消息应当是最终 JSON。
    messages = state.get("messages")
    if not messages:
        raise RuntimeError("messages 缺失，请确认 Agent 已经生成响应。")

    last_message = messages[-1]
    raw = last_message.content if isinstance(last_message.content, str) else str(last_message.content)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 非法 JSON 无法安全地作为自动审核结论，统一降级为人工审核。
        return {
            "agent_decision": "needs_review",
            "agent_reason": "Agent 输出不是合法 JSON，需要人工审核",
            "confidence": 0.0,
            "evidence": [raw[:500]],
        }

    # 将模型可能产生的未知 decision 收敛到系统支持的三个枚举值。
    decision = data.get("decision", "needs_review")
    if decision not in ["approved", "rejected", "needs_review"]:
        decision = "needs_review"

    # 模型输出不一定严格遵守数值类型；转换失败时使用最低置信度。
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    # State 对 evidence 的约定是字符串列表，对异常类型做兼容和归一化。
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
    """根据 Agent 的结论和置信度选择人工审核或自动完成。"""
    # 模型主动表示无法确定时，无论置信度是多少都必须进入人工审核。
    if state.get("agent_decision") == "needs_review":
        return "human_review"

    # 即使模型给出了 approved/rejected，置信度不足也不能直接形成最终结论。
    if state.get("confidence", 0.0) < 0.75:
        return "human_review"
    return "finalize_agent"


def finalize_agent(state: ModerationState) -> dict:
    """把可信的 Agent 阶段结论转换成统一的最终审核字段。"""
    decision = state.get("agent_decision")
    reason = state.get("agent_reason")
    if decision is None or reason is None:
        raise RuntimeError(
            "agent_decision/agent_reason 缺失，请确认已先执行 parse_agent_decision。"
        )

    return {
        "final_decision": decision,
        "final_reason": reason,
    }
