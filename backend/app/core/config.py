"""Centralised, validated application settings (Pydantic Settings).

Responsibility: load configuration from the environment, fail fast when
production configuration is missing or invalid, and expose which integrations
run in ``mock`` vs ``live`` mode. Settings never contain patient data, so
caching them is safe.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
IntegrationMode = Literal["mock", "live"]

_INSECURE_JWT_DEFAULTS = {"", "change-me", "changeme", "secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- General -----------------------------------------------------
    app_name: str = "Bindu Clinic"
    app_env: Environment = "local"
    log_level: str = "INFO"
    clinic_timezone: str = "Asia/Kolkata"
    frontend_url: str = "http://localhost:3000"
    max_request_bytes: int = Field(default=64 * 1024, ge=1024)

    # --- Database ----------------------------------------------------
    database_url: SecretStr = SecretStr("")
    database_url_unpooled: SecretStr = SecretStr("")  # direct URL for migrations

    # --- Auth / crypto -----------------------------------------------
    jwt_secret_key: SecretStr = SecretStr("")
    jwt_access_ttl_minutes: int = Field(default=15, ge=1)
    jwt_refresh_ttl_days: int = Field(default=7, ge=1, le=30)
    # Refresh-token cookie. Default: cross-site SameSite=None in staging/production, Lax locally.
    # Behind the frontend's same-origin proxy (recommended) set AUTH_COOKIE_PATH=/api/auth and
    # AUTH_COOKIE_SAMESITE=lax so the cookie is first-party (works with Safari/third-party cookie blocking).
    auth_cookie_path: str = Field(default="/auth", pattern=r"^/[A-Za-z0-9/_-]*$")
    auth_cookie_samesite: Literal["lax", "strict", "none"] | None = None
    field_encryption_key: SecretStr = SecretStr("")  # Fernet key for PII at rest
    phone_hash_key: SecretStr = SecretStr("")  # HMAC key for phone lookups
    cron_secret: SecretStr = SecretStr("")  # protects /internal/* endpoints

    # --- Grok (xAI) --------------------------------------------------
    xai_api_key: SecretStr = SecretStr("")
    xai_model: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    # --- Groq (OpenAI-compatible API). Preferred over xAI when both are configured.
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_temperature: float = Field(default=0.0, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=25)

    # --- Pinecone / embeddings ---------------------------------------
    pinecone_api_key: SecretStr = SecretStr("")
    pinecone_index_name: str = "clinic-knowledge"
    pinecone_index_host: str = ""  # optional: skips the name lookup at query time (faster cold start)
    pinecone_namespace: str = "clinic_knowledge"
    pinecone_cloud: str = "aws"  # used only when ingestion has to create the index
    pinecone_region: str = "us-east-1"
    pinecone_embed_model: str = "llama-text-embed-v2"  # Pinecone-hosted inference; same API key
    pinecone_embed_dimension: int = 1024  # must equal the index dimension

    # --- WhatsApp Cloud API ------------------------------------------
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")  # webhook signature check
    whatsapp_api_version: str = "v21.0"
    whatsapp_template_language: str = "en"
    whatsapp_timeout_seconds: float = Field(default=10.0, gt=0, le=25)

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid LOG_LEVEL")
        return v

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.app_env not in ("production", "staging"):
            return self
        missing: list[str] = []
        if not self.database_url.get_secret_value():
            missing.append("DATABASE_URL")
        if self.jwt_secret_key.get_secret_value().lower() in _INSECURE_JWT_DEFAULTS or (
            len(self.jwt_secret_key.get_secret_value()) < 32
        ):
            missing.append("JWT_SECRET_KEY (>=32 chars)")
        for name in ("field_encryption_key", "phone_hash_key", "cron_secret"):
            if not getattr(self, name).get_secret_value():
                missing.append(name.upper())
        if not self.frontend_url.startswith("https://"):
            missing.append("FRONTEND_URL (must be https)")
        if missing:
            raise ValueError("Invalid production configuration: " + ", ".join(missing))
        return self

    # --- Integration modes (mock until credentials are supplied) -----
    @property
    def llm_mode(self) -> IntegrationMode:
        return "live" if self.llm_provider else "mock"

    @property
    def llm_provider(self) -> Literal["groq", "xai", ""]:
        if self.groq_api_key.get_secret_value() and self.groq_model:
            return "groq"
        if self.xai_api_key.get_secret_value() and self.xai_model:
            return "xai"
        return ""

    @property
    def pinecone_mode(self) -> IntegrationMode:
        return "live" if self.pinecone_api_key.get_secret_value() else "mock"

    @property
    def whatsapp_mode(self) -> IntegrationMode:
        live = self.whatsapp_access_token.get_secret_value() and self.whatsapp_phone_number_id
        return "live" if live else "mock"

    @property
    def cookie_samesite(self) -> Literal["lax", "strict", "none"]:
        if self.auth_cookie_samesite:
            return self.auth_cookie_samesite
        return "none" if self.app_env in ("production", "staging") else "lax"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
