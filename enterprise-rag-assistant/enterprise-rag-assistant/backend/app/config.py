"""
Centralized application configuration.
All environment variables are loaded and validated here, once, so the rest
of the codebase never touches os.environ directly.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # Database
    database_url: str = "sqlite:///./rag_assistant.db"

    # Vector store
    chroma_persist_dir: str = "./chroma_data"
    chroma_collection_name: str = "knowledge_base"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    google_allowed_email: str = "mangavinay00@gmail.com"
    drive_folder_name: str = "AI Knowledge Base"

    # Embeddings
    embedding_provider: str = "local"  # local | openai
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    openai_api_key: str = ""

    # LLM
    llm_provider: str = "openai"  # openai | anthropic | ollama | gemini
    llm_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    # Chunking
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 75

    # Sync
    drive_poll_interval_seconds: int = 60
    max_file_size_mb: int = 20

    # Security
    session_secret: str = "dev-secret-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
