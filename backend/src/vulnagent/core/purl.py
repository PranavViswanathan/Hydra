"""Package URL (purl) construction and parsing.

Only the subset VulnAgent needs: ``pkg:<ecosystem>/<name>@<version>`` where an
npm scope's ``@`` is percent-encoded, as in ``pkg:npm/%40babel/core@7.24.0``.
"""

from __future__ import annotations

from vulnagent.core.errors import PurlError

_PREFIX = "pkg:"


def make_purl(ecosystem: str, name: str, version: str) -> str:
    if not ecosystem or not name or not version:
        raise PurlError(
            f"ecosystem, name and version are all required: {ecosystem=} {name=} {version=}"
        )
    return f"{_PREFIX}{ecosystem}/{name.replace('@', '%40', 1)}@{version}"


def parse_purl(purl: str) -> tuple[str, str, str]:
    """Return ``(ecosystem, name, version)``; raise :class:`PurlError` if malformed."""
    if not purl.startswith(_PREFIX):
        raise PurlError(f"not a purl: {purl!r}")
    ecosystem, _, remainder = purl[len(_PREFIX) :].partition("/")
    if not ecosystem or not remainder:
        raise PurlError(f"purl is missing an ecosystem or a name: {purl!r}")
    name, separator, version = remainder.rpartition("@")
    if not separator or not name or not version:
        raise PurlError(f"purl is missing a version: {purl!r}")
    return ecosystem, name.replace("%40", "@", 1), version
