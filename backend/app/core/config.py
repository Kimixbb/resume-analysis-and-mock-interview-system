from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

root_path = Path(__file__).resolve().parents[3] #项目根目录路径

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=root_path/".env",
        env_file_encoding="utf-8",
        extra="ignore" #忽视多余的配置
    )

    openai_api_key: str
    openai_base_url: str
    openai_model: str
    llm_timeout: int = 30
    database_url: str = "sqlite:///./data/app.db"

settings = Settings()