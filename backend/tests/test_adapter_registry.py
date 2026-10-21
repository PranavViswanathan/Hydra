import pytest

from vulnagent.adapters import ADAPTERS, detect_adapters
from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.errors import ConfigError

NPM_REPO = ["package.json", "package-lock.json", "src/index.ts"]


def test_the_registry_ships_the_npm_adapter():
    assert [type(adapter) for adapter in ADAPTERS] == [NpmAdapter]


def test_auto_detection_picks_the_adapter_whose_files_are_present():
    found = detect_adapters(NPM_REPO, "auto")

    assert [adapter.id for adapter in found] == ["npm"]


def test_auto_detection_finds_nothing_in_a_repository_it_does_not_understand():
    assert detect_adapters(["pom.xml", "src/Main.java"], "auto") == []


def test_an_explicit_ecosystem_list_is_honoured_when_the_files_are_there():
    found = detect_adapters(NPM_REPO, ["npm"])

    assert [adapter.id for adapter in found] == ["npm"]


def test_an_explicitly_configured_ecosystem_whose_files_are_missing_is_an_error():
    with pytest.raises(ConfigError, match="npm"):
        detect_adapters(["pom.xml"], ["npm"])


def test_an_unknown_ecosystem_name_is_an_error_rather_than_silence():
    with pytest.raises(ConfigError, match="maven"):
        detect_adapters(NPM_REPO, ["maven"])


def test_an_empty_ecosystem_list_disables_scanning():
    assert detect_adapters(NPM_REPO, []) == []
