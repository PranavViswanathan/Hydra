"""Exception types shared across the VulnAgent core."""

from __future__ import annotations


class VulnAgentError(Exception):
    """Base class for every error raised by VulnAgent itself."""


class PurlError(VulnAgentError):
    """A package URL could not be parsed or built."""


class UnsupportedLockfileError(VulnAgentError):
    """A lockfile exists but its format is not supported by the adapter."""


class ConfigError(VulnAgentError):
    """A repository's .vulnagent config is missing or invalid."""


class SafetyViolationError(VulnAgentError):
    """A proposed change violates one of the safety rules."""
