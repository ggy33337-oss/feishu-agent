from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    dashscope_api_key: str = Field(min_length=1)
    dashscope_base_url: str = Field(min_length=1)
    qwen_task_parser_model: str = Field(min_length=1)
    qwen_agent_model: str = Field(min_length=1)
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_owner_open_id: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
