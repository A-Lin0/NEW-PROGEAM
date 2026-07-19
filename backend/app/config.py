"""
应用配置读取

从环境变量或 .env 文件加载配置
"""

import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用全局配置"""

    # ---- 数据库 ----
    # 数据库类型: "sqlite" | "postgresql"
    DB_TYPE: str = "sqlite"

    # SQLite 配置（默认，零外部依赖）
    SQLITE_DB_PATH: str = "./data/app.db"

    # PostgreSQL 配置（可选，将 DB_TYPE 改为 "postgresql" 后生效）
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "admin"
    DB_PASSWORD: str = "secret"
    DB_NAME: str = "interview_db"

    @property
    def DATABASE_URL(self) -> str:
        if self.DB_TYPE == "postgresql":
            return (
                f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        return f"sqlite+aiosqlite:///{self.SQLITE_DB_PATH}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        if self.DB_TYPE == "postgresql":
            return (
                f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        return f"sqlite:///{self.SQLITE_DB_PATH}"

    # ---- Redis ----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    # ---- LLM ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    LLM_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # ---- 向量数据库 ----
    VECTOR_STORE_TYPE: str = "chroma"
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"

    # ---- JWT ----
    JWT_SECRET_KEY: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ---- 服务 ----
    BACKEND_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
