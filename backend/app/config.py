from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    APP_NAME: str = "RAG Medical Assistant"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_HOSTS: List[str] = ["*"]

    SECRET_KEY: str = Field(default="your-secret-key-change-in-production-min-32-chars")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/rag_platform")
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # LLM
    VLLM_BASE_URL: str = "http://ollama:11434/v1"
    VLLM_MODEL_NAME: str = "qwen2.5:3b-instruct"
    VLLM_API_KEY: str | None = None
    VLLM_MAX_TOKENS: int = 1024
    VLLM_TEMPERATURE: float = 0.0
    VLLM_TIMEOUT: int = 120
    VLLM_NUM_CTX: int = 4096
    LOCAL_LLM_BASE_URL: str = "http://ollama:11434/v1"
    LOCAL_LLM_MODEL_NAME: str = "qwen2.5:1.5b-instruct"
    MISTRAL_API_KEY: str | None = None
    MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
    MISTRAL_MODEL_NAME: str = "mistral-small-latest"
    MISTRAL_TIMEOUT: int = 120
    MISTRAL_MAX_TOKENS: int = 32000
    GEMINI_API_KEY: str | None = None
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT: int = 120
    GEMINI_MAX_TOKENS: int = 32000
    DEFAULT_LLM_MODE: str = "local"

    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIMENSION: int = 384
    RERANKER_MODEL: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    RERANKER_TOP_K: int = 5

    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 100
    TOP_K_RESULTS: int = 30
    SIMILARITY_THRESHOLD: float = 0.15
    MAX_CONTEXT_CHARS: int = 8000
    LLM_SECTION_DETECTION: bool = False

    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".txt", ".md", ".doc", ".docx"]
    UPLOAD_DIR: str = "/data/uploads"

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()