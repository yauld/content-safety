import re
from functools import lru_cache
from typing import Literal

import yaml

from content_safety.config import settings
from content_safety.state import ModerationState


# Workflow 层只处理低成本、确定性强的规则。
# 明确违规直接拒绝，明确安全直接放行；语义边界内容交给 Agent 深度判断。
@lru_cache
def load_rule_keywords() -> dict[str, list[str]]:
    """从 YAML 加载 Workflow 规则词，避免规则数据硬编码在业务逻辑里。"""
    with settings.rules_path.open(encoding="utf-8") as file:
        raw_rules = yaml.safe_load(file)

    if not isinstance(raw_rules, dict):
        raise ValueError(f"规则文件格式错误，顶层必须是对象：{settings.rules_path}")

    return {
        "profanity": _required_keyword_list(raw_rules, "profanity"),
        "sensitive_topics": _required_keyword_list(raw_rules, "sensitive_topics"),
        "ad_phrases": _required_keyword_list(raw_rules, "ad_phrases"),
    }


def _required_keyword_list(raw_rules: dict, key: str) -> list[str]:
    """读取并校验一个规则词列表，发现配置错误时尽早失败。"""
    value = raw_rules.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"规则文件中的 {key} 必须是字符串列表：{settings.rules_path}")
    return value


def _require_workflow_result(state: ModerationState) -> tuple[str, str]:
    """读取 Workflow 已写入的阶段性结果；缺失说明图的执行顺序被破坏。"""
    decision = state.get("workflow_decision")
    reason = state.get("workflow_reason")
    if decision is None or reason is None:
        raise RuntimeError("workflow_decision/workflow_reason 缺失，请确认已先执行 workflow_screen。")
    return decision, reason


def workflow_screen(state: ModerationState) -> dict:
    """执行规则初筛，并把命中的规则写入 state 供后续节点解释或复用。"""
    content = state["content"]
    lowered = content.lower()
    rule_keywords = load_rule_keywords()
    rule_hits: list[str] = []

    # 先收集所有命中的规则，再统一按风险优先级做决策。
    # 这样后续 Agent 或人工审核仍能看到完整的命中证据。
    if any(word.lower() in lowered for word in rule_keywords["profanity"]):
        rule_hits.append("profanity_keyword")
    if re.search(r"(.)\1{5,}", content):
        rule_hits.append("repeat_character_spam")
    if len(re.findall(r"https?://", content)) > 3 or content.count("http") > 3:
        rule_hits.append("too_many_links")
    if content.isupper() and len(content) > 20:
        rule_hits.append("all_caps_spam")
    if any(phrase.lower() in lowered for phrase in rule_keywords["ad_phrases"]):
        rule_hits.append("ad_or_fraud_phrase")
    if any(topic.lower() in lowered for topic in rule_keywords["sensitive_topics"]):
        rule_hits.append("sensitive_topic")

    # 明确不当语言属于高确定性拒绝，不需要再消耗 Agent 调用。
    if "profanity_keyword" in rule_hits:
        return {
            "workflow_decision": "rejected",
            "workflow_reason": "命中明确不当语言规则",
            "rule_hits": rule_hits,
        }

    # 垃圾内容和欺诈导流也属于规则层可以稳定处理的拒绝场景。
    spam_hits = {"repeat_character_spam", "too_many_links", "all_caps_spam", "ad_or_fraud_phrase"}
    if spam_hits.intersection(rule_hits):
        return {
            "workflow_decision": "rejected",
            "workflow_reason": "命中明确垃圾或欺诈内容规则",
            "rule_hits": rule_hits,
        }

    # 敏感话题不直接拒绝：它可能是新闻、教育、求助或正常讨论，需要 Agent 看上下文。
    if "sensitive_topic" in rule_hits:
        return {
            "workflow_decision": "needs_review",
            "workflow_reason": "命中敏感话题，需要 Agent 深度分析",
            "rule_hits": rule_hits,
        }

    # 没有明显风险信号时直接放行，避免把简单样本推给模型。
    return {
        "workflow_decision": "approved",
        "workflow_reason": "未命中明显违规规则",
        "rule_hits": rule_hits,
    }


def route_after_workflow(state: ModerationState) -> Literal["finalize_workflow", "agent"]:
    """根据规则层结论选择直接结束，或进入 Agent 深度判断。"""
    decision, _ = _require_workflow_result(state)
    if decision in ["approved", "rejected"]:
        return "finalize_workflow"
    return "agent"


def finalize_workflow(state: ModerationState) -> dict:
    """把规则层的明确结论转换成统一的最终审核结果。"""
    decision, reason = _require_workflow_result(state)
    return {
        "final_decision": decision,
        "final_reason": reason,
        "evidence": state.get("rule_hits", []),
        "confidence": 1.0,
    }
