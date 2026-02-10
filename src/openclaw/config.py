"""Application configuration via environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Fochs configuration, loaded from .env file."""

    model_config = SettingsConfigDict(
        env_prefix="FOCHS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # --- LLM (API) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    xai_api_key: str = ""
    xai_model: str = "grok-3"

    # --- LLM (Lokal - Ollama) ---
    ollama_host: str = "http://localhost:11434"
    ollama_default_model: str = "llama3.1:8b"
    ollama_fast_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Search ---
    brave_api_key: str = ""

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_allowed_users: list[int] = Field(default_factory=list)

    # --- GitHub ---
    github_token: str = ""

    # --- E-Mail ---
    email_address: str = ""
    email_imap_host: str = ""
    email_smtp_host: str = ""
    email_password: str = ""

    # --- Google Workspace ---
    google_credentials_path: str = ""

    # --- Web Dashboard ---
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_secret_key: str = "change-me"

    # --- Agent ---
    autonomy_level: str = "ask"  # full, ask, manual
    max_iterations: int = 10
    data_dir: str = "./data"

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "fochs.db")

    @property
    def chroma_path(self) -> str:
        return str(Path(self.data_dir) / "chroma")

    @property
    def log_dir(self) -> str:
        return str(Path(self.data_dir) / "logs")
