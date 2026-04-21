from enum import StrEnum

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Role(StrEnum):
    READER = "reader"
    OPERATOR = "operator"
    ADMIN = "admin"


class HttpTimeouts(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HTTP_", extra="ignore")

    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    write_timeout: float = 30.0
    max_attempts: int = Field(default=4, ge=1, le=10)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    camunda_base_url: HttpUrl
    camunda_user: str
    camunda_password: SecretStr
    camunda_engine: str = "default"

    mcp_role: Role = Role.READER

    http: HttpTimeouts = Field(default_factory=HttpTimeouts)

    @property
    def engine_rest_url(self) -> str:
        base = str(self.camunda_base_url).rstrip("/")
        return f"{base}/engine-rest"
