from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from content_safety.graph import runtime
from content_safety.schemas import (
    DecisionStage,
    ModerateRequest,
    ModerateResponse,
    ResumeRequest,
    RiskLevel,
)
from content_safety.store import store


def risk_level_for(decision: str, confidence: float | None) -> RiskLevel:
    """把审核结论和置信度转换成一个粗粒度风险等级，方便前端和业务方展示。"""
    if decision == "rejected":
        return "high"
    if decision == "needs_review":
        return "medium"
    if confidence is not None and confidence < 0.85:
        return "medium"
    return "low"


def decision_stage_for(state: dict[str, Any], is_interrupted: bool) -> DecisionStage:
    """判断本次审核结论来自哪个阶段。

    interrupted 表示 Agent 已经判断自己不能自动完成，需要转人工。
    真正人工恢复完成后，State 里会出现 human_decision。
    """
    if state.get("human_decision") is not None:
        return "human"
    if is_interrupted or state.get("agent_decision") is not None:
        return "agent"
    return "workflow"


def response_from_state(
    state: dict[str, Any],
    request: ModerateRequest,
    moderation_id: str,
    thread_id: str,
) -> ModerateResponse:
    """把 LangGraph 返回的 State 转成对外 API 响应，并写入审计存储。

    LangGraph 有两种结束形态：
    - 正常结束：State 里会有 final_decision / final_reason；
    - interrupt 暂停：State 里会有 __interrupt__，表示需要人工审核后再恢复。
    """
    interrupts = state.get("__interrupt__")
    is_interrupted = bool(interrupts)

    if is_interrupted:
        # interrupt payload 是给人工审核台看的上下文，比如原文、规则命中、Agent 证据。
        interrupt_payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        decision = "needs_review"
        reason = "需要人工审核"
        status = "interrupted"
    else:
        interrupt_payload = None
        decision = state.get("final_decision", "needs_review")
        reason = state.get("final_reason", "未生成最终原因")
        status = "completed"

    confidence = state.get("confidence")
    evidence = state.get("evidence", [])
    rule_hits = state.get("rule_hits", [])
    risk_level = risk_level_for(decision, confidence)
    decision_stage = decision_stage_for(state, is_interrupted)

    # API 响应保持稳定结构；不把完整 LangGraph State 直接暴露给业务方。
    response = ModerateResponse(
        request_id=request.request_id,
        moderation_id=moderation_id,
        thread_id=thread_id,
        status=status,
        decision=decision,
        reason=reason,
        risk_level=risk_level,
        decision_stage=decision_stage,
        evidence=evidence,
        rule_hits=rule_hits,
        confidence=confidence,
        interrupt=interrupt_payload,
    )

    # 每次审核或恢复都 upsert 一份审计记录，保证后续可以按 moderation_id/thread_id 复盘。
    store.upsert(
        {
            "request_id": request.request_id,
            "moderation_id": moderation_id,
            "thread_id": thread_id,
            "scene": request.scene,
            "user_id": request.user_id,
            "content": request.content,
            "status": response.status,
            "decision": response.decision,
            "reason": response.reason,
            "risk_level": response.risk_level,
            "decision_stage": response.decision_stage,
            "evidence": response.evidence,
            "rule_hits": response.rule_hits,
            "confidence": response.confidence,
        }
    )
    return response


def moderate(request: ModerateRequest) -> ModerateResponse:
    """首次审核入口：创建本次审核 ID，并启动 LangGraph 主链路。"""
    runtime.start()

    # moderation_id 面向业务审计；thread_id 面向 LangGraph checkpoint/resume。
    moderation_id = f"mod_{uuid4().hex}"
    thread_id = f"thread_{uuid4().hex}"

    # thread_id 必须放在 configurable 里，checkpointer 才知道这次运行属于哪个线程。
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    graph = runtime.get_graph()
    state = graph.invoke(
        {
            "content": request.content,
            "scene": request.scene,
            "user_id": request.user_id,
            "request_id": request.request_id,
            "moderation_id": moderation_id,
            "thread_id": thread_id,
        },
        config=config,
    )
    return response_from_state(state, request, moderation_id, thread_id)


def resume(thread_id: str, request: ResumeRequest) -> ModerateResponse:
    """人工审核恢复入口：把人的结论送回 interrupt 暂停点，让图继续执行。"""
    runtime.start()

    # 恢复时只拿到 thread_id，所以要先查审计记录，还原原始请求上下文。
    record = store.get_by_thread_id(thread_id)
    if record is None:
        raise KeyError(thread_id)

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # Command(resume=...) 是 LangGraph 恢复 interrupt 的固定写法。
    # 这里传入的字典会变成 human_review 节点里 interrupt(...) 的返回值。
    graph = runtime.get_graph()
    state = graph.invoke(
        Command(resume={"decision": request.decision, "reason": request.reason}),
        config=config,
    )

    # response_from_state 需要 ModerateRequest 里的 request_id/scene/user_id/content 来写审计。
    original_request = ModerateRequest(
        request_id=record.request_id,
        scene=record.scene,
        user_id=record.user_id,
        content=record.content,
    )
    return response_from_state(state, original_request, record.moderation_id, thread_id)
