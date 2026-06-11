from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "Tax-Planning-Ops"
    APP_VERSION: str = "0.1.0"
    ENV: Literal["dev", "test", "staging", "prod"] = "dev"
    DEBUG: bool = False

    @field_validator("ENV", mode="before")
    @classmethod
    def _normalize_env(cls, value: str) -> str:
        # Accept common aliases ("production"/"development") and normalize to the
        # canonical set — deploy tooling/compose often passes the long form.
        return {"production": "prod", "development": "dev", "stage": "staging"}.get(
            str(value).lower(), str(value).lower()
        )

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://tax_planning_ops_app:dev@localhost:55432/tax_planning_ops",
        description="Async DSN for the NOBYPASSRLS tax_planning_ops_app role.",
    )
    MIGRATION_DATABASE_URL: str | None = None

    WORKSPACE_GUC_NAME: str = "app.current_workspace"
    UC_UID_GUC_NAME: str = "app.uc_uid"

    KEYCLOAK_ISSUER: str = "https://auth.unicorncommander.ai/realms/uchub"
    KEYCLOAK_JWKS_URL: str = ""
    KEYCLOAK_CLIENT_ID: str = "tax-planning-ops"
    KEYCLOAK_CLIENT_SECRET: str = ""
    KEYCLOAK_AUDIENCE: str | None = None
    KEYCLOAK_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/keycloak/callback"
    FRONTEND_URL: str = "http://localhost:3000"
    JWKS_CACHE_TTL_SECONDS: int = 300
    JWT_ALLOWED_ALGORITHMS: list[str] = ["RS256"]

    STANDALONE_MODE: bool = False
    STANDALONE_WORKSPACE_ID: str = "00000000-0000-0000-0000-000000000001"
    STANDALONE_USER_ID: str = "standalone-user"

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CONTROL_PLANE_BASE_URL: str = ""
    CONTROL_PLANE_TOKEN: str = ""
    ENTITLEMENT_CHECK_ENABLED: bool = False

    MAX_UPLOAD_BYTES: int = 25_000_000  # 25 MB cap on uploaded 1040 PDFs

    GARAGE_ENDPOINT: str = "http://unicorn-garage:3900"
    GARAGE_ACCESS_KEY: str = ""
    GARAGE_SECRET_KEY: str = ""
    GARAGE_BUCKET: str = "tax-planning-ops"
    OCR_QWENVL_URL: str = ""
    OCR_QWENVL_ENABLED: bool = False
    PDF_SERVICE_URL: str = ""
    ACCOUNTING_OPS_URL: str = ""

    # LLM gateway (LiteLLM, OpenAI-compatible). Drives OCR field-structuring +
    # the planning agents. On the dev box: http://unicorn-litellm:4000/v1.
    LLM_GATEWAY_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_TEXT_MODEL: str = "qwen3.6-35b-a3b"  # agents/reasoning (thinking ON)
    # 1040 structuring: qwen3.6 with thinking OFF — faster than gemma4 (~0.8 vs
    # 1.4s, equally exact) and same model family as the agents → fewer router swaps.
    LLM_OCR_MODEL: str = "qwen3.6-35b-a3b"
    LLM_TIMEOUT_SECONDS: float = 90.0

    # Vision tier (scanned/image 1040s): a VLM served WITH a vision projector.
    # Defaults to the main gateway; point VISION_GATEWAY at the dev gateway
    # (bigboy-litellm:4001 with a `midboy1/` model prefix) or wherever the
    # mmproj-enabled model lives. Empty model disables the VLM tier.
    # Confirmed live: qwen3.6 mmproj-enabled vision at midboy1:8088 (llama-swap),
    # models Qwen3.6-35B-A3B-Vision (RTX 6000) + -p40 (P40). Set the gateway in
    # deploy: LLM_VISION_GATEWAY_URL=http://100.121.80.175:8088/v1
    LLM_VISION_GATEWAY_URL: str = ""  # falls back to LLM_GATEWAY_URL when empty
    LLM_VISION_MODEL: str = "Qwen3.6-35B-A3B-Vision"
    OCR_RENDER_DPI: int = 200

    # Alt image tier: a traditional OCR microservice (PaddleOCR/docTR on the
    # GTX 1070). POSTs page images, returns text → fed to LLM_OCR_MODEL.
    OCR_SERVICE_URL: str = ""

    @field_validator("KEYCLOAK_JWKS_URL", mode="before")
    @classmethod
    def derive_jwks_url(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        if value:
            return value
        issuer = info.data.get("KEYCLOAK_ISSUER", "")
        if issuer:
            return f"{issuer.rstrip('/')}/protocol/openid-connect/certs"
        return ""

    @field_validator("KEYCLOAK_AUDIENCE", mode="before")
    @classmethod
    def default_audience(cls, value: str | None, info) -> str:  # type: ignore[no-untyped-def]
        return value or info.data.get("KEYCLOAK_CLIENT_ID", "tax-planning-ops")

    @model_validator(mode="after")
    def fail_closed_standalone(self) -> Settings:
        if self.STANDALONE_MODE and self.ENV == "prod":
            raise ValueError("STANDALONE_MODE=true is not allowed in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
