from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StarRC FileMaker Service"
    app_env: str = "local"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:8080,http://localhost:5173,http://localhost:3000"

    database_path: str = "backend/data/app.db"
    audit_database_url: str = "postgresql://starrc:starrc@localhost:5432/starrc_audit"

    filemaker_host: str = ""
    filemaker_database: str = ""
    filemaker_username: str = ""
    filemaker_password: str = ""
    filemaker_api_version: str = "v2"
    filemaker_token_inactivity_timeout_seconds: int = Field(
        default=15 * 60,
        validation_alias=AliasChoices(
            "FILEMAKER_TOKEN_INACTIVITY_TIMEOUT_SECONDS",
            "FILEMAKER_TOKEN_TTL_SECONDS",
        ),
    )
    filemaker_timeout_seconds: float = 30.0
    filemaker_ssl_verify: bool = False
    filemaker_read_only: bool = True

    webviewer_context_secret: str = "dev-webviewer-secret-change-me"
    webviewer_session_ttl_seconds: int = 8 * 60 * 60
    webviewer_allow_mock_context: bool = True

    mes_callback_api_key: str = ""
    mes_hmac_secret: str = ""
    mes_filemaker_layout: str = ""
    mes_filemaker_script_name: str = "MES_UpdateWorkOrder"
    callback_max_attempts: int = 8
    callback_poll_interval_seconds: float = 5.0

    qr_base_url: str = "http://localhost:8080/q"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def filemaker_configured(self) -> bool:
        return all(
            [
                self.filemaker_host,
                self.filemaker_database,
                self.filemaker_username,
                self.filemaker_password,
            ]
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
