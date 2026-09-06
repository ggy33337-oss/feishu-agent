# -*- coding: utf-8 -*-
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    dashscope_api_key: str = Field(min_length=1)
    dashscope_base_url: str = Field(min_length=1)
    qwen_task_parser_model: str = Field(min_length=1)
    qwen_agent_model: str = Field(min_length=1)
    qwen_router_model: str = "qwen3.8-flash"
    qwen_translator_model: str = "qwen-plus"
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    serper_key_id: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    admin_api_key: str = ""
    task_queue_poll_seconds: float = Field(default=0.25, gt=0)
    task_queue_max_attempts: int = Field(default=3, ge=1, le=10)
    task_worker_concurrency: int = Field(default=4, ge=1, le=32)
    task_queue_max_wait_seconds: int = Field(default=300, ge=30, le=86400)
    database_url: str = "mysql+aiomysql://root:password@localhost:3306/news_app?charset=utf8mb4"
    database_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_pool_recycle: int = Field(default=1800, ge=60)
    # Deprecated compatibility setting; production uses DATABASE_URL.
    task_queue_path: str = ""
    artifact_root: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
