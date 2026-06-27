from typing import Annotated, Literal, Required, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# 内容安全服务对外只暴露三种审核结论。
Decision = Literal["approved", "rejected", "needs_review"]


class ModerationState(TypedDict, total=False):
    """LangGraph 在各个节点之间传递的共享状态。

    total=False 表示大多数字段可以逐步补齐：入口只传入 content/scene 等基础字段，
    后续节点再陆续写入 Workflow 结论、Agent 证据、人工审核结果和最终结论。
    content 使用 Required 标出入口不变量，避免节点读取原文时被静态检查器误报。
    """

    # 入口字段：由 /moderate 请求和 service.moderate 写入。
    content: Required[str]  # 待审核的原始内容，比如评论、帖子、昵称或私信文本。
    scene: str  # 业务场景标识，比如 comment、post、profile，用于后续按场景调整策略。
    user_id: str | None  # 提交内容的用户 ID；MVP 里只做记录，后续可接用户风险画像。
    request_id: str | None  # 业务方传入的请求 ID，方便调用方把审核结果和自己的请求对上。
    moderation_id: str  # 内容安全服务生成的审核记录 ID，用于查询和审计。
    thread_id: str  # LangGraph checkpoint 线程 ID，用于 interrupt 后从暂停点 resume。

    # Workflow 层字段：由 workflow_screen 写入，用于快速规则初筛和后续审计。
    workflow_decision: Decision  # Workflow 规则初筛给出的结论：通过、拒绝或转深度审核。
    workflow_reason: str  # Workflow 给出该结论的原因，比如命中垃圾链接或敏感话题规则。
    rule_hits: list[str]  # Workflow 命中的规则列表，用于解释、审计和前端展示。

    # Agent 层字段。
    # messages 使用 add_messages reducer，多个节点返回新消息时会追加到历史消息里，
    # 这正是 ToolNode/LLM 工具循环需要的对话状态。
    messages: Annotated[list[AnyMessage], add_messages]  # Agent 对话历史，保存系统提示、用户内容、工具调用和工具结果。
    agent_decision: Decision  # Agent 基于语义分析和工具证据给出的审核结论。
    agent_reason: str  # Agent 给出结论的自然语言原因，最终可能展示给审核人员或业务方。
    confidence: float  # Agent 对自己结论的置信度；低于阈值会转人工审核。
    evidence: list[str]  # Agent 汇总的证据列表，比如政策命中、上下文线索、工具扫描结果。

    # 人工审核字段：human_review 从 interrupt 恢复后写入。
    human_decision: Decision  # 人工审核员恢复 interrupt 时提交的最终判断。
    human_reason: str  # 人工审核员填写的判断原因，用于最终响应和审计。

    # 最终输出字段：finalize_* 节点写入，service.py 会把它转换成 API 响应。
    final_decision: Decision  # 对外返回的最终审核结论，可能来自 Workflow、Agent 或人工审核。
    final_reason: str  # 对外返回的最终原因，和 final_decision 一起进入 API 响应。
