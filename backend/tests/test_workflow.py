from content_safety.workflow import workflow_screen


def test_workflow_approves_normal_content():
    result = workflow_screen({"content": "这是一条正常的产品体验评论。"})

    assert result["workflow_decision"] == "approved"
    assert result["rule_hits"] == []


def test_workflow_rejects_spam_content():
    result = workflow_screen({"content": "AAAAAAAAAAAAAAAAAAA 点击领取 http://a http://b http://c http://d"})

    assert result["workflow_decision"] == "rejected"
    assert "repeat_character_spam" in result["rule_hits"]


def test_workflow_rejects_configured_ad_phrase():
    result = workflow_screen({"content": "兼职刷单返佣，秒到账无门槛，私聊我带你赚钱。"})

    assert result["workflow_decision"] == "rejected"
    assert "ad_or_fraud_phrase" in result["rule_hits"]


def test_workflow_rejects_configured_profanity_keyword():
    result = workflow_screen({"content": "你这个傻叉，别再发了。"})

    assert result["workflow_decision"] == "rejected"
    assert "profanity_keyword" in result["rule_hits"]


def test_workflow_routes_sensitive_content_to_agent():
    result = workflow_screen({"content": "这篇文章讨论暴力事件的新闻报道方式。"})

    assert result["workflow_decision"] == "needs_review"
    assert "sensitive_topic" in result["rule_hits"]


def test_workflow_routes_configured_sensitive_topic_to_agent():
    result = workflow_screen({"content": "新闻稿提到一起枪击和爆炸事件，重点讨论公共安全提醒。"})

    assert result["workflow_decision"] == "needs_review"
    assert "sensitive_topic" in result["rule_hits"]
