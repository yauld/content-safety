from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from content_safety.config import settings
from content_safety.graph import runtime
from content_safety.schemas import (
    DashboardSummary,
    ModerateRequest,
    ModerateResponse,
    ModerationRecord,
    ResumeRequest,
    ReviewSummary,
)
from content_safety.service import moderate, resume
from content_safety.store import store


# FastAPI lifespan 只负责应用级资源的准备和释放：
# - 准备 data 目录和 SQLite 表；
# - 启动 LangGraph runtime，让 checkpoint saver 在整个进程内复用；
# - 进程关闭时释放 runtime 持有的连接。
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_storage:
        settings.data_path.mkdir(parents=True, exist_ok=True)
        store.setup()
    runtime.start()
    yield
    runtime.stop()


# 这是后端服务的唯一 FastAPI 应用实例。
# 业务逻辑尽量放在 service / graph / workflow / agent 等模块里，
# main.py 只保留 HTTP 入口、错误转换和应用装配。
app = FastAPI(
    title="Content Safety API",
    version="0.1.0",
    description="MVP content moderation service.",
    lifespan=lifespan,
)

# 允许前端审核台调用 API。来源列表来自 CONTENT_SAFETY_CORS_ORIGINS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """给本地开发、部署探活和前端联调用的健康检查接口。"""
    return {"status": "ok", "service": "content-safety-api"}


@app.post("/moderate", response_model=ModerateResponse, tags=["moderation"])
def moderate_content(request: ModerateRequest) -> ModerateResponse:
    """内容安全核心入口：业务系统提交内容，从这里进入 Workflow + Agent 主链路。"""
    return moderate(request)


@app.get("/moderate/{moderation_id}", response_model=ModerationRecord, tags=["moderation"])
def get_moderation(moderation_id: str) -> ModerationRecord:
    """按 moderation_id 查询一次审核记录，主要用于排查和审计。"""
    record = store.get_by_moderation_id(moderation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="moderation record not found")
    return record


@app.get("/reviews/pending", response_model=list[ModerationRecord], tags=["reviews"])
def list_pending_reviews() -> list[ModerationRecord]:
    """给内部审核台使用：列出当前因 interrupt 暂停、等待人工结论的内容。"""
    return store.list_pending()


@app.get("/reviews/summary", response_model=ReviewSummary, tags=["reviews"])
def review_summary() -> ReviewSummary:
    """给审核台顶部统计卡使用：返回待审、高风险和今日处理概览。"""
    return store.review_summary()


@app.get("/reviews/recent", response_model=list[ModerationRecord], tags=["reviews"])
def list_recent_reviews(limit: int = Query(default=20, ge=1, le=100)) -> list[ModerationRecord]:
    """给审核台最近处理记录使用，默认返回最近 20 条，最多 100 条。"""
    return store.list_recent(limit=limit)


@app.get("/dashboard/summary", response_model=DashboardSummary, tags=["dashboard"])
def dashboard_summary() -> DashboardSummary:
    """给数据看板使用：返回 Workflow / Agent / Human 三层聚合统计。"""
    return store.dashboard_summary()


@app.post("/moderate/{thread_id}/resume", response_model=ModerateResponse, tags=["reviews"])
def resume_moderation(thread_id: str, request: ResumeRequest) -> ModerateResponse:
    """人工审核恢复入口：用 thread_id 找回 checkpoint，并从中断点继续执行图。"""
    try:
        return resume(thread_id, request)
    except KeyError:
        raise HTTPException(status_code=404, detail="thread not found") from None


def main() -> None:
    """命令行入口：`uv run content-safety-api` 会调用这里启动开发服务。"""
    import uvicorn

    uvicorn.run(
        "content_safety.main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        reload_dirs=["src"],
    )
