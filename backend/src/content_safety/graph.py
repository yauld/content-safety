from contextlib import AbstractContextManager

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from content_safety.agent import (
    agent_assistant,
    enter_agent,
    finalize_agent,
    parse_agent_decision,
    route_after_agent,
)
from content_safety.config import settings
from content_safety.review import finalize_human, human_review
from content_safety.state import ModerationState
from content_safety.tools import TOOLS
from content_safety.workflow import finalize_workflow, route_after_workflow, workflow_screen


def build_graph(checkpointer):
    """组装内容安全主图。

    主链路是：
    Workflow 规则初筛 -> 明确结论直接结束；边界内容进入 Agent；
    Agent 可以循环调用工具；低置信度或 needs_review 进入人工审核。
    """
    builder = StateGraph(ModerationState)

    # Workflow 层：便宜、稳定、可解释，负责处理明显通过/明显拒绝。
    builder.add_node("workflow_screen", workflow_screen)
    builder.add_node("finalize_workflow", finalize_workflow)

    # Agent 层：处理 Workflow 说不清的边界内容。
    builder.add_node("enter_agent", enter_agent)
    builder.add_node("agent_assistant", agent_assistant)

    # ToolNode 会读取 AIMessage.tool_calls，执行 TOOLS 中对应的 Python 工具，
    # 再把工具结果写回 messages，供下一轮 agent_assistant 继续推理。
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node("parse_agent_decision", parse_agent_decision)

    # 人工审核层：human_review 内部会调用 interrupt()，让图暂停等待人工结论。
    builder.add_node("human_review", human_review)
    builder.add_node("finalize_agent", finalize_agent)
    builder.add_node("finalize_human", finalize_human)

    # 入口永远先走规则初筛。
    builder.add_edge(START, "workflow_screen")

    # Workflow 的条件边：
    # - approved/rejected：直接转成最终结果；
    # - needs_review：进入 Agent 深度判断。
    builder.add_conditional_edges(
        "workflow_screen",
        route_after_workflow,
        {
            "finalize_workflow": "finalize_workflow",
            "agent": "enter_agent",
        },
    )
    builder.add_edge("finalize_workflow", END)

    # 进入 Agent 前先写入 SystemMessage/HumanMessage，准备模型上下文。
    builder.add_edge("enter_agent", "agent_assistant")

    # ReAct 风格工具循环：
    # - 如果模型输出 tool_calls，tools_condition 返回 "tools"；
    # - 如果模型没有工具调用，说明它输出了最终 JSON，进入解析节点。
    builder.add_conditional_edges(
        "agent_assistant",
        tools_condition,
        {
            "tools": "tools",
            "__end__": "parse_agent_decision",
        },
    )

    # 工具执行完成后回到模型节点，让 Agent 读取工具结果后继续判断。
    builder.add_edge("tools", "agent_assistant")

    # 解析 Agent JSON 之后，根据 decision/confidence 决定是否需要人工审核。
    builder.add_conditional_edges(
        "parse_agent_decision",
        route_after_agent,
        {
            "human_review": "human_review",
            "finalize_agent": "finalize_agent",
        },
    )

    # 人工审核恢复后，finalize_human 会把人的结论写成 final_decision。
    builder.add_edge("human_review", "finalize_human")
    builder.add_edge("finalize_agent", END)
    builder.add_edge("finalize_human", END)

    # checkpointer 是 interrupt/resume 的基础。没有它，人工审核暂停后就无法恢复。
    return builder.compile(checkpointer=checkpointer)


class GraphRuntime:
    """保存编译后的图和 SQLite checkpoint 连接。

    FastAPI 进程启动时创建一次 runtime；每次请求复用同一个 graph/checkpointer。
    这样 /moderate 暂停后，/moderate/{thread_id}/resume 才能用同一个 checkpoint
    找回之前的执行状态。

    SqliteSaver.from_conn_string(...) 的常规写法是 with 语句：

        with SqliteSaver.from_conn_string("checkpoints.sqlite3") as checkpointer:
            graph = build_graph(checkpointer)

    但 FastAPI 服务不能把它包在短生命周期的 with 代码块里。with 一结束，
    SQLite 连接就会关闭；而服务运行期间，/moderate 和 /resume 都需要持续使用
    同一个 checkpointer。因此这里把 context manager 保存到 _saver_cm，在 start()
    时手动 __enter__()，在 stop() 时手动 __exit__()。
    """

    def __init__(self) -> None:
        settings.data_path.mkdir(parents=True, exist_ok=True)
        self._saver_cm: AbstractContextManager | None = None
        self.checkpointer = None
        self.graph: CompiledStateGraph | None = None

    def start(self) -> None:
        """初始化 checkpoint saver 并编译图；重复调用是安全的。"""
        if self.graph is not None:
            return

        # 第 1 步：确定 checkpoint 数据库文件路径。
        # 这个 SQLite 文件只保存 LangGraph 的执行快照，不保存业务审计记录。
        checkpoint_db_path = settings.checkpoint_db_path

        # 第 2 步：把 Path 转成连接字符串。
        # SqliteSaver 这里接收的是 str，所以不要直接传 Path 对象。
        checkpoint_conn_string = str(checkpoint_db_path)

        # 第 3 步：创建 SQLite saver 的 context manager。
        # from_conn_string(...) 返回的不是最终 checkpointer，而是一个类似 with 的上下文对象。
        # 这里必须把它保存到 self._saver_cm，否则后面 stop() 时就没法关闭 SQLite 连接。
        saver_context = SqliteSaver.from_conn_string(checkpoint_conn_string)

        # 第 4 步：手动进入 context manager，拿到真正传给 LangGraph 的 checkpointer。
        # 这里不用 with，是因为 FastAPI 启动后要一直持有连接，直到应用关闭时再释放。
        self._saver_cm = saver_context
        self.checkpointer = self._saver_cm.__enter__()

        # 第 5 步：创建 LangGraph checkpoint 所需的 SQLite 表。
        # 如果表已经存在，setup() 会保持可重复执行。
        self.checkpointer.setup()

        # 第 6 步：用这个 checkpointer 编译图。
        # 有了它，interrupt 暂停后的 State 才能按 thread_id 恢复。
        self.graph = build_graph(self.checkpointer)

    def get_graph(self) -> CompiledStateGraph:
        """返回已经编译好的图；如果还没启动，就先初始化 runtime。"""
        self.start()
        if self.graph is None:
            raise RuntimeError("GraphRuntime 启动失败，graph 仍然为空。")
        return self.graph

    def stop(self) -> None:
        """关闭 checkpoint saver，释放 SQLite 连接。"""
        if self._saver_cm is not None:
            self._saver_cm.__exit__(None, None, None)
        self._saver_cm = None
        self.checkpointer = None
        self.graph = None


# main.py 从这里导入单例 runtime；不要在每个请求里重新创建 GraphRuntime。
runtime = GraphRuntime()
