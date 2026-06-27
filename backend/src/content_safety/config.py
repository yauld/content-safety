from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置。

    pydantic-settings 会按 env_prefix 自动读取环境变量：
    CONTENT_SAFETY_MODEL -> model
    CONTENT_SAFETY_DATA_DIR -> data_dir
    """

    model_config = SettingsConfigDict(
        # 所有环境变量都使用 CONTENT_SAFETY_ 前缀，避免和其他项目配置混在一起。
        env_prefix="CONTENT_SAFETY_",
        # 本地开发优先读取 backend/.env；从项目根目录启动时也允许读取 ../.env。
        env_file=(".env", "../.env"),
        # .env 里出现未定义字段时忽略，方便多个本地项目共用配置文件。
        extra="ignore",
    )

    # 所有本地运行产生的数据都放在 data_dir 下，包括 SQLite 和 JSONL 审计日志。
    data_dir: Path = Path("../data")

    # Workflow 规则词配置文件。可用 CONTENT_SAFETY_RULES_FILE 覆盖。
    rules_file: Path = BACKEND_DIR / "config" / "rules.yaml"

    # MVP 阶段固定使用本地 Ollama 模型，后续可通过 CONTENT_SAFETY_MODEL 切换。
    model: str = "qwen3-coder:30b"

    # 允许调用 API 的前端来源。多个来源用英文逗号分隔。
    cors_origins: str = "http://localhost:5173"

    # 开发期自动创建 SQLite 表；生产环境更适合用 migration 管理。
    auto_create_storage: bool = True

    @property
    def data_path(self) -> Path:
        """归一化后的数据目录绝对路径。"""
        return self.data_dir.resolve()

    @property
    def rules_path(self) -> Path:
        """归一化后的规则词配置文件路径。"""
        return self.rules_file.resolve()

    @property
    def audit_db_path(self) -> Path:
        """业务审计 SQLite 文件：保存 moderation record。"""
        return self.data_path / "content_safety.sqlite3"

    @property
    def checkpoint_db_path(self) -> Path:
        """LangGraph checkpoint SQLite 文件：支持 interrupt 后按 thread_id 恢复。"""
        return self.data_path / "checkpoints.sqlite3"

    @property
    def audit_jsonl_path(self) -> Path:
        """追加式审计日志，方便 MVP 阶段直接查看每次审核过程。"""
        return self.data_path / "audit.jsonl"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置转换成 FastAPI 需要的列表。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次 import 都重新读取环境变量和 .env。"""
    return Settings()


# 模块级单例。其他模块直接 import settings，保持配置入口统一。
settings = get_settings()
