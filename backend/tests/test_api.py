from fastapi.testclient import TestClient

from content_safety.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_moderate_normal_content_completes_without_llm():
    with TestClient(app) as client:
        response = client.post(
            "/moderate",
            json={
                "request_id": "test-normal",
                "scene": "comment",
                "user_id": "u-test",
                "content": "这是一条正常的产品体验评论。",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["decision"] == "approved"
    assert body["decision_stage"] == "workflow"


def test_moderate_profanity_content_uses_workflow_stage():
    with TestClient(app) as client:
        response = client.post(
            "/moderate",
            json={
                "request_id": "test-profanity",
                "scene": "comment",
                "user_id": "u-test",
                "content": "这条内容包含敏感词，应该被规则直接拦截。",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["decision"] == "rejected"
    assert body["decision_stage"] == "workflow"
    assert body["rule_hits"] == ["profanity_keyword"]


def test_moderate_sensitive_content_uses_agent_stage():
    with TestClient(app) as client:
        response = client.post(
            "/moderate",
            json={
                "request_id": "test-sensitive",
                "scene": "comment",
                "user_id": "u-test",
                "content": "这篇文章讨论暴力事件的新闻报道方式是否合适。",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision_stage"] == "agent"
    assert body["rule_hits"] == ["sensitive_topic"]


def test_resume_interrupted_content_uses_human_stage():
    with TestClient(app) as client:
        first = client.post(
            "/moderate",
            json={
                "request_id": "test-human",
                "scene": "comment",
                "user_id": "u-test",
                "content": "我想写一段关于自伤的内容，不确定应该怎么表达，你能帮我整理一下吗？",
            },
        )
        first_body = first.json()

        assert first.status_code == 200
        assert first_body["status"] == "interrupted"
        assert first_body["decision_stage"] == "agent"

        second = client.post(
            f"/moderate/{first_body['thread_id']}/resume",
            json={
                "decision": "approved",
                "reason": "人工判断为求助或创作咨询语境，可以通过。",
            },
        )

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["status"] == "completed"
    assert second_body["decision"] == "approved"
    assert second_body["decision_stage"] == "human"


def test_review_dashboard_endpoints():
    with TestClient(app) as client:
        summary = client.get("/reviews/summary")
        recent = client.get("/reviews/recent")

    assert summary.status_code == 200
    summary_body = summary.json()
    assert {
        "pending_total",
        "pending_max_wait_seconds",
        "pending_agent",
        "completed_today",
    }.issubset(summary_body)
    assert recent.status_code == 200
    assert isinstance(recent.json(), list)


def test_dashboard_summary_endpoint():
    with TestClient(app) as client:
        response = client.get("/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert {
        "total_requests",
        "workflow",
        "agent",
        "human",
        "rule_hits",
        "risk_levels",
        "decision_stages",
        "confidence_buckets",
        "waiting_buckets",
    }.issubset(body)
