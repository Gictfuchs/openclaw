"""Application configuration via environment variables."""

import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    web_port: int = Field(default=8080, ge=1, le=65535)
    web_secret_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_hex(32)))
    web_session_key: SecretStr = Field(default_factory=lambda: SecretStr(secrets.token_hex(32)))
    debug: bool = False

    # --- Agent ---
    autonomy_level: Literal["full", "ask", "manual"] = "full"
    max_iterations: int = Field(default=10, ge=1, le=100)
    data_dir: str = "./data"

    # --- Shell / Maschinenautonomie ---
    shell_mode: Literal["restricted", "standard", "unrestricted"] = "restricted"
    shell_timeout: int = Field(default=30, ge=1, le=300)
    shell_allowed_dirs: list[str] = Field(default_factory=lambda: ["/opt/fochs", "/tmp/fochs"])
    plugins_dir: str = "./plugins"

    # --- Security / Budget ---
    daily_token_budget: int = Field(default=500_000, ge=0)
    monthly_token_budget: int = Field(default=10_000_000, ge=0)
    max_tokens_per_run: int = Field(default=50_000, ge=0)
    proactive_message_limit: int = Field(default=50, ge=0)

    # --- Credential Vault (ClosedClaw) ---
    closedclaw_vault_path: str = ""
    closedclaw_backend: str = "vault-file"
    closedclaw_unlock_timeout: int = Field(default=300, ge=30, le=3600)

    # --- Composio (Brokered Credentials) ---
    composio_api_key: SecretStr = SecretStr("")
    composio_base_url: str = "https://backend.composio.dev/api/v2"

    # --- ClawHub (Skill Marketplace) ---
    clawhub_api_key: SecretStr = SecretStr("")
    clawhub_base_url: str = "https://api.clawhub.ai/v1"
    clawhub_auto_scan: bool = True

    # --- VirusTotal (Security Scanning) ---
    virustotal_api_key: SecretStr = SecretStr("")

    # --- Honcho (Memory Layer) ---
    honcho_api_key: SecretStr = SecretStr("")
    honcho_base_url: str = "https://api.honcho.dev/v1"
    honcho_app_id: str = ""

    # --- AgentMail (Agent Email API) ---
    agentmail_api_key: SecretStr = SecretStr("")
    agentmail_base_url: str = "https://api.agentmail.to/v1"

    @field_validator("shell_allowed_dirs")
    @classmethod
    def validate_allowed_dirs(cls, v: list[str]) -> list[str]:
        """Ensure at least one allowed directory is configured."""
        if not v:
            msg = "shell_allowed_dirs must contain at least one directory"
            raise ValueError(msg)
        return v

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "fochs.db")

    @property
    def chroma_path(self) -> str:
        return str(Path(self.data_dir) / "chroma")

    @property
    def log_dir(self) -> str:
        return str(Path(self.data_dir) / "logs")
