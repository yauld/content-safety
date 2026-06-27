#!/usr/bin/env python3
"""Export the current content safety LangGraph as a business-friendly PNG image.

The script reuses the real build_graph(...) function from src/content_safety/graph.py,
so the generated image reflects the graph structure currently used by the backend.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from content_safety.graph import build_graph


DEFAULT_OUTPUT_PATH = Path("docs/content-safety-graph.png")
FONT_NAME = "PingFang SC"

EXPECTED_EDGES = {
    ("__start__", "workflow_screen"),
    ("workflow_screen", "finalize_workflow"),
    ("workflow_screen", "enter_agent"),
    ("finalize_workflow", "__end__"),
    ("enter_agent", "agent_assistant"),
    ("agent_assistant", "tools"),
    ("tools", "agent_assistant"),
    ("agent_assistant", "parse_agent_decision"),
    ("parse_agent_decision", "human_review"),
    ("parse_agent_decision", "finalize_agent"),
    ("human_review", "finalize_human"),
    ("finalize_agent", "__end__"),
    ("finalize_human", "__end__"),
}


def compiled_graph_view():
    """Compile the real project graph with an in-memory checkpointer for visualization."""
    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer)
    return graph.get_graph()


def validate_current_graph(view) -> None:
    """Keep the explanatory diagram honest when build_graph(...) changes."""
    actual_edges = {(edge.source, edge.target) for edge in view.edges}
    if actual_edges == EXPECTED_EDGES:
        return

    missing = EXPECTED_EDGES - actual_edges
    unexpected = actual_edges - EXPECTED_EDGES
    details = []
    if missing:
        details.append(f"missing expected edges: {sorted(missing)}")
    if unexpected:
        details.append(f"unexpected current edges: {sorted(unexpected)}")
    raise SystemExit(
        "The business diagram template no longer matches build_graph(...). "
        "Update backend/scripts/export_graph.py before exporting.\n"
        + "\n".join(details)
    )


def add_node(graph, name: str, label: str, fill: str, shape: str = "rect") -> None:
    graph.add_node(
        name,
        label=label,
        shape=shape,
        style="rounded,filled",
        fillcolor=fill,
        color="#334155",
        penwidth="1.4",
        fontname=FONT_NAME,
        fontsize="14",
        margin="0.14,0.09",
    )


def add_edge(
    graph,
    source: str,
    target: str,
    label: str = "",
    color: str = "#475569",
    style: str = "solid",
) -> None:
    graph.add_edge(
        source,
        target,
        label=label,
        color=color,
        fontcolor=color,
        fontname=FONT_NAME,
        fontsize="11",
        arrowsize="0.8",
        penwidth="1.5",
        style=style,
    )


def build_business_diagram():
    """Build a readable Graphviz view that explains the current business flow."""
    try:
        import pygraphviz as pgv
    except ImportError as exc:
        message = (
            "PNG export needs Graphviz + pygraphviz. Install them first:\n"
            "  brew install graphviz\n"
            "  uv add --dev pygraphviz\n\n"
            f"Original error: {exc}"
        )
        raise SystemExit(message) from exc

    graph = pgv.AGraph(
        directed=True,
        strict=False,
        rankdir="TB",
        bgcolor="#ffffff",
        pad="0.35",
        nodesep="0.45",
        ranksep="0.72",
        splines="spline",
        outputorder="edgesfirst",
    )
    graph.graph_attr.update(
        label="Content Safety 审核主流程",
        labelloc="t",
        labeljust="c",
        fontname=FONT_NAME,
        fontsize="22",
        fontcolor="#0f172a",
    )
    graph.node_attr.update(fontname=FONT_NAME)
    graph.edge_attr.update(fontname=FONT_NAME)

    add_node(graph, "__start__", "Start\n接收审核请求", "#dbeafe", shape="oval")
    add_node(graph, "__end__", "End\n输出 final_decision", "#dcfce7", shape="oval")

    workflow = graph.add_subgraph(
        ["workflow_screen", "finalize_workflow"],
        name="cluster_workflow",
        label="1. Workflow 规则初筛",
        color="#f59e0b",
        style="rounded",
        penwidth="1.8",
        fontname=FONT_NAME,
        fontsize="15",
        fontcolor="#92400e",
    )
    add_node(
        workflow,
        "workflow_screen",
        "workflow_screen\n规则初筛\n关键词 / 广告 / 链接 / 敏感话题",
        "#fef3c7",
    )
    add_node(
        workflow,
        "finalize_workflow",
        "finalize_workflow\n明确通过或拒绝\nconfidence = 1.0",
        "#fffbeb",
    )

    agent = graph.add_subgraph(
        ["enter_agent", "agent_assistant", "tools", "parse_agent_decision", "finalize_agent"],
        name="cluster_agent",
        label="2. Agent 深度判断",
        color="#2563eb",
        style="rounded",
        penwidth="1.8",
        fontname=FONT_NAME,
        fontsize="15",
        fontcolor="#1d4ed8",
    )
    add_node(agent, "enter_agent", "enter_agent\n组装 System/Human 消息\n带入初筛证据", "#dbeafe")
    add_node(agent, "agent_assistant", "agent_assistant\nLLM 推理\n可选择调用工具", "#dbeafe")
    add_node(agent, "tools", "tools\n执行工具\n补充政策/信号/上下文", "#e0f2fe")
    add_node(
        agent,
        "parse_agent_decision",
        "parse_agent_decision\n解析最终 JSON\n校验 decision / confidence",
        "#dbeafe",
    )
    add_node(agent, "finalize_agent", "finalize_agent\n写入 Agent 结论", "#eff6ff")

    human = graph.add_subgraph(
        ["human_review", "finalize_human"],
        name="cluster_human",
        label="3. 人工审核",
        color="#9333ea",
        style="rounded",
        penwidth="1.8",
        fontname=FONT_NAME,
        fontsize="15",
        fontcolor="#7e22ce",
    )
    add_node(human, "human_review", "human_review\ninterrupt 暂停\n等待人工审核", "#f3e8ff")
    add_node(human, "finalize_human", "finalize_human\n写入人工结论", "#faf5ff")

    add_edge(graph, "__start__", "workflow_screen", "所有请求先初筛")
    add_edge(
        graph,
        "workflow_screen",
        "finalize_workflow",
        "approved / rejected\n明显放行或拒绝",
        "#b45309",
    )
    add_edge(
        graph,
        "workflow_screen",
        "enter_agent",
        "needs_review\n敏感或边界内容",
        "#2563eb",
        "dashed",
    )
    add_edge(graph, "finalize_workflow", "__end__", "规则层最终结果")

    add_edge(graph, "enter_agent", "agent_assistant", "准备模型上下文", "#2563eb")
    add_edge(graph, "agent_assistant", "tools", "tool_calls\n需要更多证据", "#0284c7", "dashed")
    add_edge(graph, "tools", "agent_assistant", "工具结果\n继续推理", "#0284c7")
    add_edge(
        graph,
        "agent_assistant",
        "parse_agent_decision",
        "无工具调用\n输出最终 JSON",
        "#2563eb",
        "dashed",
    )
    add_edge(
        graph,
        "parse_agent_decision",
        "finalize_agent",
        "approved / rejected\n且 confidence >= 0.75",
        "#16a34a",
        "dashed",
    )
    add_edge(
        graph,
        "parse_agent_decision",
        "human_review",
        "needs_review\n或 confidence < 0.75",
        "#9333ea",
        "dashed",
    )
    add_edge(graph, "finalize_agent", "__end__", "Agent 最终结果")

    add_edge(graph, "human_review", "finalize_human", "人工提交结论", "#9333ea")
    add_edge(graph, "finalize_human", "__end__", "人工最终结果")

    return graph


def export_png(path: Path) -> None:
    """Export the current graph to a readable PNG file through Graphviz/pygraphviz."""
    view = compiled_graph_view()
    validate_current_graph(view)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = build_business_diagram()
    graph.draw(str(path), prog="dot", format="png")
    print(f"PNG graph written to: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the current content safety LangGraph PNG.")
    parser.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT_PATH),
        help="PNG output path. Defaults to docs/content-safety-graph.png.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export_png(Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
