"""Application configuration via environment variables."""

import secrets
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Fochs configuration, loaded from .env file."""

    model_config = SettingsConfigDict(
        env_prefix="FOCHS_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # --- LLM (API) ---
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    xai_api_key: SecretStr = SecretStr("")
    xai_model: str = "grok-3"

    # --- LLM (Lokal - Ollama) ---
    ollama_host: str = "http://localhost:11434"
    ollama_default_model: str = "llama3.1:8b"
    ollama_fast_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Search ---
    brave_api_key: SecretStr = SecretStr("")

    # --- Telegram ---
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_allowed_users: list[int] = Field(default_factory=list)

    # --- GitHub ---
    github_token: SecretStr = SecretStr("")

    # --- E-Mail ---
    email_address: str = ""
    email_imap_host: str = ""
    email_smtp_host: str = ""
    email_password: SecretStr = SecretStr("")

    # --- Google Workspace ---
    google_credentials_path: str = ""

    # --- Web Dashboard ---
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_hex(32)))

    # --- Agent ---
    autonomy_level: str = "full"  # full, ask, manual
    max_iterations: int = 10
    data_dir: str = "./data"

    # --- Security / Budget ---
    daily_token_budget: int = 500_000  # Max tokens per day across all providers
    monthly_token_budget: int = 10_000_000
    max_tokens_per_run: int = 50_000  # Max tokens for a single agent run
    proactive_message_limit: int = 50  # Max proactive messages per user per day

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "fochs.db")

    @property
    def chroma_path(self) -> str:
        return str(Path(self.data_dir) / "chroma")

    @property
    def log_dir(self) -> str:
        return str(Path(self.data_dir) / "logs")
