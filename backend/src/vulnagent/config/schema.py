"""The `.vulnagent.yml` / `.vulnagent.json` repository config (§13.1).

An invalid config is never a crash: :func:`parse_repo_config` raises
:class:`ConfigError` with a message meant to be stored on the repo row and
shown verbatim on the dashboard.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Literal, Self

import yaml
from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vulnagent.core.errors import ConfigError
from vulnagent.core.models import Threshold

CONFIG_FILENAMES: tuple[str, ...] = (".vulnagent.yml", ".vulnagent.yaml", ".vulnagent.json")

# §11 rule 7: whatever the repo asks for, the agent never retries CI more than this.
MAX_CI_RETRIES_CEILING = 5

_STRICT = ConfigDict(extra="forbid")


class IgnoreRule(BaseModel):
    model_config = _STRICT

    id: str
    reason: str
    expires: dt.date | None = None

    def applies_on(self, day: dt.date) -> bool:
        return self.expires is None or day <= self.expires


class ScanConfig(BaseModel):
    model_config = _STRICT

    schedule: str | None = "0 6 * * *"  # cron, UTC; null disables scheduled scans
    on_push: bool = True
    on_new_advisory: bool = True

    @field_validator("schedule")
    @classmethod
    def _reject_invalid_cron(cls, value: str | None) -> str | None:
        if value is not None and not croniter.is_valid(value):
            raise ValueError(f"not a valid cron expression: {value!r}")
        return value


class AgentConfig(BaseModel):
    model_config = _STRICT

    auto_start: bool = True
    severity_threshold: Threshold = "high"
    max_ci_retries: int = Field(default=3, ge=0, le=MAX_CI_RETRIES_CEILING)
    auto_merge: bool = False
    allow_major_bumps: bool = False
    grouping: Literal["single_pr", "per_package"] = "single_pr"
    ignore: list[IgnoreRule] = Field(default_factory=list)


class RepoConfig(BaseModel):
    model_config = _STRICT

    version: Literal[1] = 1
    enabled: bool = True
    ecosystems: Literal["auto"] | list[str] = "auto"
    paths: list[str] = Field(default_factory=lambda: ["."])
    scan: ScanConfig = Field(default_factory=ScanConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    @field_validator("paths")
    @classmethod
    def _reject_paths_beyond_the_root(cls, value: list[str]) -> list[str]:
        if value != ["."]:
            raise ValueError('only paths: ["."] is supported for now')
        return value

    def is_ignored(self, osv_id: str, *, on: dt.date) -> bool:
        return any(
            rule.id.casefold() == osv_id.casefold() and rule.applies_on(on)
            for rule in self.agent.ignore
        )

    @classmethod
    def defaults(cls) -> Self:
        return cls()


def parse_repo_config(text: str, *, path: str) -> RepoConfig:
    """Parse a config file's contents. Raises :class:`ConfigError` if unusable."""
    raw = _load(text, path=path)
    if raw is None:
        return RepoConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level, got {type(raw).__name__}")
    try:
        return RepoConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"{path}: {_describe(error)}") from error


def _load(text: str, *, path: str) -> object:
    if path.endswith(".json"):
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ConfigError(f"{path}: invalid JSON: {error}") from error
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path}: invalid YAML: {error}") from error


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
        for item in error.errors()
    )
