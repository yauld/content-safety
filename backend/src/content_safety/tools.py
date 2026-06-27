import re

from langchain_core.tools import tool


POLICY_TEXT = {
    "self_harm": "自伤内容：鼓励、指导或美化自伤行为时拒绝；求助或康复讨论应转人工。",
    "violence": "暴力内容：具体伤害指导、威胁、煽动暴力时拒绝；新闻、教育、反暴力讨论可通过或转人工。",
    "sexual": "色情内容：露骨性内容、未成年人相关性内容应拒绝；健康教育语境需谨慎判断。",
    "spam": "垃圾内容：批量广告、诱导点击、刷屏、欺诈链接应拒绝。",
}


@tool
def lookup_policy(category: str) -> str:
    """查询某个内容安全类别的审核政策。category 可取 self_harm、violence、sexual、spam。"""
    return POLICY_TEXT.get(category, "未找到该类别政策，请转人工审核。")


@tool
def scan_spam_signals(content: str) -> str:
    """扫描内容中的垃圾信息信号，返回命中的模式。"""
    signals = []
    if len(re.findall(r"https?://", content)) > 3:
        signals.append("链接过多")
    if re.search(r"(.)\1{5,}", content):
        signals.append("重复字符刷屏")
    if re.search(r"(加微信|免费提现|限时返利|点击领取|代理加盟)", content):
        signals.append("疑似广告或欺诈话术")
    return "、".join(signals) if signals else "未发现明显垃圾信息信号"


@tool
def collect_context(content: str) -> str:
    """提取内容中的上下文线索，帮助判断是违规、讨论、求助还是教育场景。"""
    hints = []
    if any(word in content for word in ["如何", "教程", "步骤", "具体做法"]):
        hints.append("可能包含操作性指导")
    if any(word in content for word in ["新闻", "讨论", "研究", "历史", "科普"]):
        hints.append("可能是讨论或教育语境")
    if any(word in content for word in ["救命", "求助", "怎么办", "我想伤害自己"]):
        hints.append("可能是求助语境")
    return "、".join(hints) if hints else "未发现明确上下文线索"


TOOLS = [lookup_policy, scan_spam_signals, collect_context]

