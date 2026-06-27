#!/usr/bin/env python3
"""模拟一个业务系统调用内容安全服务。

这个脚本只通过 HTTP 调用 Content Safety API，不依赖后端内部实现。
它代表真实业务方的接入方式：提交内容，读取审核结论，然后决定发布、拦截或进入待审核。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BusinessContent:
    name: str
    scene: str
    user_id: str
    content: str
    expected: str
    expected_rule_hit: str | None = None


DEFAULT_CASES = [
    # 明确低风险：应由 Workflow 快速通过。
    BusinessContent(
        name="正常产品评论",
        scene="comment",
        user_id="user_normal_001",
        content="这是一条正常的产品体验评论，整体使用很顺畅，希望后续增加深色模式。",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="普通文章草稿",
        scene="article_draft",
        user_id="user_normal_002",
        content="本文整理了团队协作中的需求确认、任务拆分和复盘方法，适合新同事入门阅读。",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="客服咨询",
        scene="chat",
        user_id="user_normal_003",
        content="你好，我想咨询一下会员到期后如何续费，以及是否支持开发票。",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="正常吐槽但无违规",
        scene="comment",
        user_id="user_normal_004",
        content="这个版本的加载速度有点慢，希望后续优化一下首页响应时间。",
        expected="completed / approved / workflow",
    ),
    # 明确垃圾/欺诈：应由 Workflow 直接拒绝。
    BusinessContent(
        name="多链接福利广告",
        scene="comment",
        user_id="user_spam_001",
        content="点击领取福利 http://a.com http://b.com http://c.com http://d.com",
        expected="completed / rejected / workflow",
        expected_rule_hit="ad_or_fraud_phrase",
    ),
    BusinessContent(
        name="广告诱导加微信",
        scene="comment",
        user_id="user_spam_002",
        content="加微信领取内部资料，限时返利，免费提现，错过今天就没有了。",
        expected="completed / rejected / workflow",
        expected_rule_hit="ad_or_fraud_phrase",
    ),
    BusinessContent(
        name="重复字符刷屏",
        scene="comment",
        user_id="user_spam_003",
        content="AAAAAAAAAAAAAAAAAAAAA 买买买！！！",
        expected="completed / rejected / workflow",
    ),
    BusinessContent(
        name="代理加盟广告",
        scene="comment",
        user_id="user_spam_004",
        content="代理加盟，日入过千，点击领取专属名额，马上联系。",
        expected="completed / rejected / workflow",
        expected_rule_hit="ad_or_fraud_phrase",
    ),
    BusinessContent(
        name="刷单返佣广告",
        scene="direct_message",
        user_id="user_spam_005",
        content="兼职刷单返佣，秒到账无门槛，私聊我带你赚钱。",
        expected="completed / rejected / workflow",
        expected_rule_hit="ad_or_fraud_phrase",
    ),
    BusinessContent(
        name="加 V 拉群广告",
        scene="profile_bio",
        user_id="user_spam_006",
        content="加V进群领取内部名额，高额返利，月入过万不是梦。",
        expected="completed / rejected / workflow",
        expected_rule_hit="ad_or_fraud_phrase",
    ),
    # 明确不当语言：应由 Workflow 直接拒绝。
    BusinessContent(
        name="命中不当语言：敏感词",
        scene="comment",
        user_id="user_abuse_001",
        content="这条内容包含敏感词，应该被规则直接拦截。",
        expected="completed / rejected / workflow",
        expected_rule_hit="profanity_keyword",
    ),
    BusinessContent(
        name="命中不当语言：辱骂词",
        scene="comment",
        user_id="user_abuse_002",
        content="你这个傻叉，别再发这种评论了。",
        expected="completed / rejected / workflow",
        expected_rule_hit="profanity_keyword",
    ),
    BusinessContent(
        name="命中不当语言：粗口变体",
        scene="comment",
        user_id="user_abuse_003",
        content="他妈的，这个回复也太离谱了。",
        expected="completed / rejected / workflow",
        expected_rule_hit="profanity_keyword",
    ),
    BusinessContent(
        name="命中不当语言：攻击表达",
        scene="direct_message",
        user_id="user_abuse_004",
        content="你就是个废物，赶紧滚蛋。",
        expected="completed / rejected / workflow",
        expected_rule_hit="profanity_keyword",
    ),
    # 敏感但可能合规：通常进入 Agent，Agent 可通过或转人工。
    BusinessContent(
        name="暴力新闻报道讨论",
        scene="article_draft",
        user_id="user_sensitive_001",
        content="这篇文章讨论暴力事件的新闻报道方式是否合适。",
        expected="agent 判断，可能 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="自伤表达协助请求",
        scene="article_draft",
        user_id="user_sensitive_002",
        content="我想写一段关于自伤的内容，不确定应该怎么表达，你能帮我整理一下吗？",
        expected="interrupted / needs_review / agent",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="心理健康教育语境",
        scene="article_draft",
        user_id="user_sensitive_003",
        content="这篇科普文章介绍如何识别自杀风险信号，并建议读者及时联系专业机构。",
        expected="agent 判断，通常 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="政治话题中性讨论",
        scene="article_draft",
        user_id="user_sensitive_004",
        content="这篇文章从公共政策角度讨论政治新闻报道中的事实核查方法。",
        expected="agent 判断，通常 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="成人话题学术讨论",
        scene="article_draft",
        user_id="user_sensitive_005",
        content="这篇健康教育内容讨论色情内容对青少年媒介素养教育的影响。",
        expected="agent 判断，通常 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="公共事件讨论",
        scene="forum_post",
        user_id="user_sensitive_006",
        content="这个帖子讨论近期游行和抗议事件中的信息核验问题。",
        expected="agent 判断，通常 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="暴力犯罪新闻",
        scene="article_draft",
        user_id="user_sensitive_007",
        content="新闻稿提到一起枪击和爆炸事件，重点讨论公共安全提醒。",
        expected="agent 判断，通常 approved 或 needs_review",
        expected_rule_hit="sensitive_topic",
    ),
    BusinessContent(
        name="心理危机求助",
        scene="chat",
        user_id="user_sensitive_008",
        content="我最近总是想死，感觉自己不想活了。",
        expected="interrupted / needs_review / agent",
        expected_rule_hit="sensitive_topic",
    ),
    # 边界和上下文不足：应暴露 Agent/人工分流效果。
    BusinessContent(
        name="上下文不足的求助",
        scene="chat",
        user_id="user_edge_001",
        content="我现在很难受，不知道还能不能撑下去，你能陪我说几句吗？",
        expected="可能 needs_review / agent",
    ),
    BusinessContent(
        name="引用违规词进行说明",
        scene="article_draft",
        user_id="user_edge_002",
        content="文章里引用了敏感词这个词本身，用来解释为什么平台规则会拦截。",
        expected="当前规则会 workflow 拒绝，用于观察规则误伤",
    ),
    BusinessContent(
        name="疑似营销但链接少",
        scene="comment",
        user_id="user_edge_003",
        content="这个活动看起来挺划算的，可以去官网看看详情 http://example.com",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="短文本无上下文",
        scene="comment",
        user_id="user_edge_004",
        content="太猛了，受不了了。",
        expected="completed / approved / workflow，观察短文本漏判风险",
    ),
    BusinessContent(
        name="混合正常和敏感话题",
        scene="article_draft",
        user_id="user_edge_005",
        content="我在写一篇影评，里面提到暴力场景如何服务叙事，而不是鼓励现实模仿。",
        expected="agent 判断，通常 approved 或 needs_review",
    ),
    # 不同业务场景：同一内容在不同业务线可以观察后续策略扩展空间。
    BusinessContent(
        name="私信里的普通预约",
        scene="direct_message",
        user_id="user_scene_001",
        content="明天下午三点方便开会吗？我想确认一下需求范围。",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="昵称资料简介广告",
        scene="profile_bio",
        user_id="user_scene_002",
        content="加微信获取免费提现教程，限时返利，代理加盟名额有限。",
        expected="completed / rejected / workflow",
    ),
    BusinessContent(
        name="工单投诉",
        scene="support_ticket",
        user_id="user_scene_003",
        content="我对这次服务很不满意，请尽快帮我处理退款问题。",
        expected="completed / approved / workflow",
    ),
    BusinessContent(
        name="论坛标题党",
        scene="forum_post",
        user_id="user_scene_004",
        content="震惊！这个功能竟然让我省了一半时间，真实体验分享。",
        expected="completed / approved / workflow",
    ),
]


RULE_FLAGS = {
    "profanity": "profanity_keyword",
    "sensitive_topics": "sensitive_topic",
    "ad_phrases": "ad_or_fraud_phrase",
}

API_CANDIDATES = [
    "http://localhost:8002",
    "http://127.0.0.1:8002",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
]


def get_json(url: str, timeout: float = 2) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


def discover_api_base() -> str:
    """自动寻找本地启动的内容安全服务。"""
    for api_base in API_CANDIDATES:
        health = get_json(f"{api_base}/health")
        if health.get("status") == "ok":
            return api_base
    raise RuntimeError(
        "没有找到可用的内容安全服务。请先启动后端，例如：cd backend && uv run content-safety-api"
    )


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        raise RuntimeError(f"HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接内容安全服务：{error.reason}") from error


def business_action(result: dict[str, Any]) -> str:
    """把内容安全返回结果转换成业务系统自己的动作。"""
    status = result["status"]
    decision = result["decision"]

    if status == "interrupted" or decision == "needs_review":
        return "进入业务待审核状态，不立即发布"
    if decision == "approved":
        return "允许发布"
    if decision == "rejected":
        return "拒绝发布，并提示用户修改"
    return "未知结果，按保守策略进入待审核"


def submit_content(api_base: str, item: BusinessContent, index: int) -> None:
    request_id = f"mock-business-{int(time.time() * 1000)}-{index}"
    payload = {
        "request_id": request_id,
        "scene": item.scene,
        "user_id": item.user_id,
        "content": item.content,
    }
    result = post_json(f"{api_base.rstrip('/')}/moderate", payload)

    print("=" * 88)
    print(f"用例编号: {index}")
    print(f"用例名称: {item.name}")
    print(f"测试预期: {item.expected}")
    print(f"业务请求 ID: {request_id}")
    print(f"业务场景: {item.scene}")
    print(f"用户 ID: {item.user_id}")
    print(f"提交内容: {item.content}")
    print("-" * 88)
    print(f"审核状态: {result['status']}")
    print(f"审核结论: {result['decision']}")
    print(f"判断阶段: {result.get('decision_stage')}")
    print(f"风险等级: {result['risk_level']}")
    print(f"原因: {result['reason']}")
    print(f"业务动作: {business_action(result)}")
    rule_hits = result.get("rule_hits", [])
    if rule_hits:
        print(f"规则命中: {', '.join(rule_hits)}")
    if item.expected_rule_hit:
        matched = item.expected_rule_hit in rule_hits
        status = "PASS" if matched else "FAIL"
        print(f"期望规则: {item.expected_rule_hit} -> {status}")
    if result.get("evidence"):
        print(f"证据: {' | '.join(str(item) for item in result['evidence'])}")
    if result["status"] == "interrupted":
        print(f"待人工审核 thread_id: {result['thread_id']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="模拟业务系统调用内容安全 /moderate 接口")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--profanity", action="store_true", help="验证 profanity_keyword 规则")
    group.add_argument("--sensitive-topics", action="store_true", help="验证 sensitive_topic 规则")
    group.add_argument("--ad-phrases", action="store_true", help="验证 ad_or_fraud_phrase 规则")
    group.add_argument("--all", action="store_true", help="运行全部默认用例")
    return parser.parse_args()


def selected_cases(args: argparse.Namespace) -> list[BusinessContent]:
    if args.all:
        return DEFAULT_CASES
    if args.profanity:
        rule_hit = RULE_FLAGS["profanity"]
    elif args.sensitive_topics:
        rule_hit = RULE_FLAGS["sensitive_topics"]
    else:
        rule_hit = RULE_FLAGS["ad_phrases"]
    return [item for item in DEFAULT_CASES if item.expected_rule_hit == rule_hit]


def main() -> int:
    args = parse_args()
    cases = selected_cases(args)

    try:
        api_base = discover_api_base()
        print(f"已找到内容安全服务: {api_base}")
        for offset, item in enumerate(cases, start=0):
            submit_content(api_base, item, offset + 1)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
