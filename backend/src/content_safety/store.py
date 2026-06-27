import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from content_safety.config import settings
from content_safety.schemas import DashboardMetricGroup, DashboardSummary, ModerationRecord, ReviewSummary


def utc_now() -> str:
    """返回统一的 UTC 时间字符串，避免不同机器本地时区导致审计时间混乱。"""
    return datetime.now(UTC).isoformat()


class ModerationStore:
    """内容安全业务记录存储。

    这里保存的是“审核业务数据”：原文、结论、原因、风险等级、阶段、证据和时间。
    它和 LangGraph checkpoint 不是一回事：
    - checkpoint SQLite：保存图执行状态，用于 interrupt/resume；
    - audit SQLite/JSONL：保存可查询、可审计、可展示给审核台的业务记录。
    """

    def __init__(self, db_path: Path, jsonl_path: Path) -> None:
        # db_path 是审核台查询用的 SQLite 数据库。
        self.db_path = db_path
        # jsonl_path 是追加式审计日志，便于以后做离线分析或回放。
        self.jsonl_path = jsonl_path

    def connect(self) -> sqlite3.Connection:
        """创建一次 SQLite 连接，并把查询结果设置成可按字段名读取的 Row。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def setup(self) -> None:
        """初始化审核记录表。

        FastAPI 启动时会调用它。MVP 阶段我们用 SQLite，不额外引入迁移工具，
        所以这里同时承担“建表”和少量兼容旧表结构的职责。
        """
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_records (
                    moderation_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL UNIQUE,
                    request_id TEXT,
                    scene TEXT NOT NULL,
                    user_id TEXT,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    decision_stage TEXT NOT NULL DEFAULT 'workflow',
                    evidence_json TEXT NOT NULL,
                    rule_hits_json TEXT NOT NULL,
                    confidence REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_decision_stage_column(conn)
            conn.commit()

    def _ensure_decision_stage_column(self, conn: sqlite3.Connection) -> None:
        """兼容早期本地数据库：如果缺少 decision_stage，就补上这一列。"""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(moderation_records)")}
        if "decision_stage" not in columns:
            conn.execute(
                "ALTER TABLE moderation_records "
                "ADD COLUMN decision_stage TEXT NOT NULL DEFAULT 'workflow'"
            )

    def upsert(self, record: dict[str, Any]) -> None:
        """新增或更新一条审核记录。

        /moderate 首次审核会写入一条记录；如果内容进入人工审核，/resume 完成后会用
        同一个 moderation_id 更新原记录的状态、结论和阶段。
        """
        now = utc_now()
        # 新记录使用当前时间作为 created_at；更新已有记录时保留调用方传入的 created_at。
        created_at = record.get("created_at") or now
        # updated_at 表示这条记录最后一次状态变化时间。
        updated_at = now
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO moderation_records (
                    moderation_id, thread_id, request_id, scene, user_id, content,
                    status, decision, reason, risk_level, decision_stage, evidence_json, rule_hits_json,
                    confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(moderation_id) DO UPDATE SET
                    status=excluded.status,
                    decision=excluded.decision,
                    reason=excluded.reason,
                    risk_level=excluded.risk_level,
                    decision_stage=excluded.decision_stage,
                    evidence_json=excluded.evidence_json,
                    rule_hits_json=excluded.rule_hits_json,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (
                    record["moderation_id"],
                    record["thread_id"],
                    record.get("request_id"),
                    record.get("scene", "default"),
                    record.get("user_id"),
                    record["content"],
                    record["status"],
                    record["decision"],
                    record["reason"],
                    record["risk_level"],
                    record.get("decision_stage", "workflow"),
                    # SQLite 没有原生 list 字段，这里把证据和规则命中序列化成 JSON 字符串。
                    json.dumps(record.get("evidence", []), ensure_ascii=False),
                    json.dumps(record.get("rule_hits", []), ensure_ascii=False),
                    record.get("confidence"),
                    created_at,
                    updated_at,
                ),
            )
            conn.commit()

        # JSONL 是追加日志，即使 SQLite 记录被 upsert 覆盖，历史状态变化仍然能保留下来。
        self.append_jsonl({**record, "created_at": created_at, "updated_at": updated_at})

    def append_jsonl(self, record: dict[str, Any]) -> None:
        """把审核事件追加到 JSONL 审计日志中。"""
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_by_thread_id(self, thread_id: str) -> ModerationRecord | None:
        """按 LangGraph thread_id 查询记录，主要给 /moderate/{thread_id}/resume 使用。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM moderation_records WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_moderation_id(self, moderation_id: str) -> ModerationRecord | None:
        """按业务审计 ID 查询记录，主要给 GET /moderate/{moderation_id} 使用。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM moderation_records WHERE moderation_id = ?",
                (moderation_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_pending(self) -> list[ModerationRecord]:
        """列出等待人工审核的记录，供审核工作台左侧队列使用。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM moderation_records
                WHERE status = 'interrupted'
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_recent(self, limit: int = 5) -> list[ModerationRecord]:
        """列出最近更新的审核记录，供处理记录页使用。"""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM moderation_records
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def review_summary(self) -> ReviewSummary:
        """计算审核台顶部统计卡片的数据。"""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.connect() as conn:
            # 当前还停在 interrupt 状态的记录，就是待人工审核总数。
            pending_total = conn.execute(
                "SELECT COUNT(*) FROM moderation_records WHERE status = 'interrupted'"
            ).fetchone()[0]

            # 找最早进入待审的记录，用它计算“最长等待”。没有待审记录时为 0。
            oldest_pending_created_at = conn.execute(
                """
                SELECT MIN(created_at) FROM moderation_records
                WHERE status = 'interrupted'
                """
            ).fetchone()[0]
            pending_max_wait_seconds = 0
            if oldest_pending_created_at:
                oldest_pending = datetime.fromisoformat(oldest_pending_created_at)
                pending_max_wait_seconds = max(
                    0,
                    int((datetime.now(UTC) - oldest_pending).total_seconds()),
                )

            # Agent 转人工数量能体现模型无法自动判断、需要人工兜底的规模。
            pending_agent = conn.execute(
                """
                SELECT COUNT(*) FROM moderation_records
                WHERE status = 'interrupted' AND decision_stage = 'agent'
                """
            ).fetchone()[0]

            # 今日已处理用于粗略观察当天吞吐量。这里按 UTC 日期统计，MVP 阶段先保持简单。
            completed_today = conn.execute(
                """
                SELECT COUNT(*) FROM moderation_records
                WHERE status = 'completed' AND updated_at >= ?
                """,
                (today_start,),
            ).fetchone()[0]
        return ReviewSummary(
            pending_total=pending_total,
            pending_max_wait_seconds=pending_max_wait_seconds,
            pending_agent=pending_agent,
            completed_today=completed_today,
        )

    def dashboard_summary(self) -> DashboardSummary:
        """计算数据看板所需的 Workflow / Agent / Human 聚合指标。"""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        now = datetime.now(UTC)
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM moderation_records").fetchall()
            completed_today = conn.execute(
                """
                SELECT COUNT(*) FROM moderation_records
                WHERE status = 'completed' AND updated_at >= ?
                """,
                (today_start,),
            ).fetchone()[0]

        records = [dict(row) for row in rows]
        total_requests = len(records)
        completed_total = sum(1 for item in records if item["status"] == "completed")
        interrupted_total = sum(1 for item in records if item["status"] == "interrupted")

        stage_counter = Counter(item["decision_stage"] for item in records)
        risk_counter = Counter(item["risk_level"] for item in records)
        rule_counter: Counter[str] = Counter()
        confidence_counter: Counter[str] = Counter()
        waiting_counter: Counter[str] = Counter()

        for item in records:
            rule_counter.update(json.loads(item["rule_hits_json"]))
            confidence = item["confidence"]
            if confidence is not None:
                confidence_counter[self._confidence_bucket(float(confidence))] += 1
            if item["status"] == "interrupted":
                created_at = datetime.fromisoformat(item["created_at"])
                wait_seconds = max(0, int((now - created_at).total_seconds()))
                waiting_counter[self._waiting_bucket(wait_seconds)] += 1

        pending_created_times = [
            datetime.fromisoformat(item["created_at"])
            for item in records
            if item["status"] == "interrupted"
        ]
        pending_max_wait_seconds = 0
        if pending_created_times:
            pending_max_wait_seconds = max(
                0,
                int((now - min(pending_created_times)).total_seconds()),
            )

        workflow = self._metric_group(records, "workflow")
        agent = self._metric_group(records, "agent")
        human = self._metric_group(records, "human")
        auto_completed_total = workflow.approved + workflow.rejected + agent.approved + agent.rejected
        human_involved_total = human.total + interrupted_total

        return DashboardSummary(
            total_requests=total_requests,
            completed_total=completed_total,
            interrupted_total=interrupted_total,
            auto_completed_total=auto_completed_total,
            human_involved_total=human_involved_total,
            workflow=workflow,
            agent=agent,
            human=human,
            pending_total=interrupted_total,
            pending_max_wait_seconds=pending_max_wait_seconds,
            completed_today=completed_today,
            rule_hits=dict(rule_counter.most_common()),
            risk_levels={key: risk_counter.get(key, 0) for key in ["low", "medium", "high"]},
            decision_stages={key: stage_counter.get(key, 0) for key in ["workflow", "agent", "human"]},
            confidence_buckets={
                key: confidence_counter.get(key, 0)
                for key in ["0-0.5", "0.5-0.75", "0.75-0.9", "0.9-1.0"]
            },
            waiting_buckets={
                key: waiting_counter.get(key, 0)
                for key in ["0-5分钟", "5-30分钟", "30-120分钟", "2小时以上"]
            },
        )

    def _metric_group(self, records: list[dict[str, Any]], stage: str) -> DashboardMetricGroup:
        """按审核阶段统计结论分布。"""
        items = [item for item in records if item["decision_stage"] == stage]
        decision_counter = Counter(item["decision"] for item in items)
        return DashboardMetricGroup(
            total=len(items),
            approved=decision_counter.get("approved", 0),
            rejected=decision_counter.get("rejected", 0),
            needs_review=decision_counter.get("needs_review", 0),
        )

    def _confidence_bucket(self, confidence: float) -> str:
        if confidence < 0.5:
            return "0-0.5"
        if confidence < 0.75:
            return "0.5-0.75"
        if confidence < 0.9:
            return "0.75-0.9"
        return "0.9-1.0"

    def _waiting_bucket(self, seconds: int) -> str:
        if seconds < 5 * 60:
            return "0-5分钟"
        if seconds < 30 * 60:
            return "5-30分钟"
        if seconds < 2 * 60 * 60:
            return "30-120分钟"
        return "2小时以上"

    def _row_to_record(self, row: sqlite3.Row) -> ModerationRecord:
        """把 SQLite Row 转换成 API 层使用的 Pydantic 模型。"""
        data = dict(row)
        return ModerationRecord(
            request_id=data["request_id"],
            moderation_id=data["moderation_id"],
            thread_id=data["thread_id"],
            scene=data["scene"],
            user_id=data["user_id"],
            content=data["content"],
            status=data["status"],
            decision=data["decision"],
            reason=data["reason"],
            risk_level=data["risk_level"],
            decision_stage=data.get("decision_stage", "workflow"),
            evidence=json.loads(data["evidence_json"]),
            rule_hits=json.loads(data["rule_hits_json"]),
            confidence=data["confidence"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# 全局单例：service.py 和 main.py 复用同一个 store 配置即可；连接仍然按方法短连接创建。
store = ModerationStore(settings.audit_db_path, settings.audit_jsonl_path)
