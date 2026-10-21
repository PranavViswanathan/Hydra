"""Process settings read from the environment (§13.2).

Only the Appwrite and GitHub App credentials are required: a deployment that
just scans should boot without LLM or embedding keys, so those are optional and
the code that needs them asks via :meth:`Settings.require_llm` /
:meth:`Settings.require_embeddings` and fails with the variable's name.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vulnagent.core.errors import ConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    appwrite_endpoint: str
    appwrite_project_id: str
    appwrite_api_key: SecretStr

    github_app_id: int
    github_app_private_key: SecretStr
    github_webhook_secret: SecretStr
    github_app_slug: str | None = None

    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    embedding_api_key: SecretStr | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None

    osv_base_url: str = "https://api.osv.dev"

    npm_lockfile_function_id: str | None = Field(default=None)

    @field_validator("github_app_private_key", mode="before")
    @classmethod
    def _unescape_pem_newlines(cls, value: Any) -> Any:
        """Accept a PEM pasted as one line with literal ``\\n`` escapes."""
        if isinstance(value, str) and "\\n" in value:
            return value.replace("\\n", "\n")
        return value

    @field_validator("osv_base_url", "appwrite_endpoint")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    def require_llm(self) -> tuple[SecretStr, str]:
        if self.llm_api_key is None:
            raise ConfigError("LLM_API_KEY is not set")
        if not self.llm_model:
            raise ConfigError("LLM_MODEL is not set")
        return self.llm_api_key, self.llm_model

    def require_embeddings(self) -> tuple[SecretStr, str, int]:
        if self.embedding_api_key is None:
            raise ConfigError("EMBEDDING_API_KEY is not set")
        if not self.embedding_model:
            raise ConfigError("EMBEDDING_MODEL is not set")
        if self.embedding_dim is None:
            raise ConfigError("EMBEDDING_DIM is not set")
        return self.embedding_api_key, self.embedding_model, self.embedding_dim

    def require_npm_lockfile_function_id(self) -> str:
        if not self.npm_lockfile_function_id:
            raise ConfigError("NPM_LOCKFILE_FUNCTION_ID is not set")
        return self.npm_lockfile_function_id


def load_settings(*, dotenv: str | None = None, **overrides: Any) -> Settings:
    """Build :class:`Settings`, reporting missing variables by their env var name.

    Deployed functions get their variables from the platform, so nothing is read
    from disk unless a caller (a local script) asks for ``dotenv=".env"``.
    """
    try:
        # pydantic's dataclass_transform hides BaseSettings' own init keywords,
        # of which _env_file is one, from type checkers.
        return Settings(_env_file=dotenv, **overrides)  # type: ignore[call-arg]
    except ValidationError as error:
        raise ConfigError(_describe(error)) from error


def _describe(error: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
        for item in error.errors()
    )
    return f"invalid environment configuration: {problems}"
