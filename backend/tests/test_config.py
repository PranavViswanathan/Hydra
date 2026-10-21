import datetime as dt

import pytest

from vulnagent.config.schema import RepoConfig, parse_repo_config
from vulnagent.core.errors import ConfigError

MINIMAL = "version: 1\n"


def test_an_empty_config_file_still_yields_the_documented_defaults():
    config = parse_repo_config(MINIMAL, path=".vulnagent.yml")

    assert config.enabled is True
    assert config.ecosystems == "auto"
    assert config.paths == ["."]
    assert config.scan.schedule == "0 6 * * *"
    assert config.scan.on_push is True
    assert config.scan.on_new_advisory is True
    assert config.agent.auto_start is True
    assert config.agent.severity_threshold == "high"
    assert config.agent.max_ci_retries == 3
    assert config.agent.auto_merge is False
    assert config.agent.allow_major_bumps is False
    assert config.agent.grouping == "single_pr"
    assert config.agent.ignore == []


def test_reads_the_full_example_from_the_spec():
    config = parse_repo_config(
        """
        version: 1
        enabled: true
        ecosystems: [npm]
        paths: ["."]
        scan:
          schedule: "0 6 * * *"
          on_push: true
          on_new_advisory: true
        agent:
          auto_start: true
          severity_threshold: high
          max_ci_retries: 3
          auto_merge: false
          allow_major_bumps: false
          grouping: single_pr
          ignore:
            - id: GHSA-xxxx-xxxx-xxxx
              reason: "Not reachable in our usage"
              expires: 2026-12-31
        """,
        path=".vulnagent.yml",
    )

    assert config.ecosystems == ["npm"]
    assert config.agent.ignore[0].id == "GHSA-xxxx-xxxx-xxxx"
    assert config.agent.ignore[0].expires == dt.date(2026, 12, 31)


def test_reads_the_json_flavour_of_the_config():
    config = parse_repo_config(
        '{"version": 1, "agent": {"auto_merge": true}}', path=".vulnagent.json"
    )

    assert config.agent.auto_merge is True


def test_a_schedule_of_null_disables_scheduled_scans():
    config = parse_repo_config("version: 1\nscan:\n  schedule: null\n", path=".vulnagent.yml")

    assert config.scan.schedule is None


def test_rejects_a_schedule_that_is_not_a_valid_cron_expression():
    with pytest.raises(ConfigError, match="schedule"):
        parse_repo_config("version: 1\nscan:\n  schedule: 'every morning'\n", path=".vulnagent.yml")


def test_rejects_a_retry_count_above_the_hard_ceiling_of_five():
    with pytest.raises(ConfigError, match="max_ci_retries"):
        parse_repo_config("version: 1\nagent:\n  max_ci_retries: 9\n", path=".vulnagent.yml")


def test_accepts_the_hard_ceiling_itself():
    config = parse_repo_config("version: 1\nagent:\n  max_ci_retries: 5\n", path=".vulnagent.yml")

    assert config.agent.max_ci_retries == 5


def test_rejects_an_unknown_severity_threshold():
    with pytest.raises(ConfigError, match="severity_threshold"):
        parse_repo_config(
            "version: 1\nagent:\n  severity_threshold: spicy\n", path=".vulnagent.yml"
        )


def test_rejects_an_unknown_top_level_key_so_typos_are_not_silently_ignored():
    with pytest.raises(ConfigError, match="enabeld"):
        parse_repo_config("version: 1\nenabeld: false\n", path=".vulnagent.yml")


def test_rejects_a_config_version_the_agent_does_not_understand():
    with pytest.raises(ConfigError, match="version"):
        parse_repo_config("version: 2\n", path=".vulnagent.yml")


def test_rejects_a_file_that_is_not_a_mapping():
    with pytest.raises(ConfigError):
        parse_repo_config("- just\n- a\n- list\n", path=".vulnagent.yml")


def test_rejects_malformed_yaml_rather_than_raising_a_yaml_error():
    with pytest.raises(ConfigError):
        parse_repo_config("version: 1\n  bad: [indent\n", path=".vulnagent.yml")


def test_an_empty_file_is_treated_as_an_all_defaults_config():
    assert parse_repo_config("", path=".vulnagent.yml") == RepoConfig()


def test_mvp_only_supports_scanning_the_repository_root():
    with pytest.raises(ConfigError, match="paths"):
        parse_repo_config('version: 1\npaths: ["packages/api"]\n', path=".vulnagent.yml")


def test_yaml_loading_does_not_construct_arbitrary_python_objects():
    with pytest.raises(ConfigError):
        parse_repo_config("!!python/object/apply:os.system ['echo pwned']\n", path=".vulnagent.yml")


def test_an_ignore_rule_without_an_expiry_never_expires():
    config = parse_repo_config(
        "version: 1\nagent:\n  ignore:\n    - id: GHSA-aaaa-bbbb-cccc\n      reason: accepted\n",
        path=".vulnagent.yml",
    )

    assert config.is_ignored("GHSA-aaaa-bbbb-cccc", on=dt.date(2099, 1, 1)) is True


def test_an_ignore_rule_stops_applying_the_day_after_it_expires():
    config = parse_repo_config(
        "version: 1\nagent:\n  ignore:\n"
        "    - id: GHSA-aaaa-bbbb-cccc\n      reason: temporary\n      expires: 2026-12-31\n",
        path=".vulnagent.yml",
    )

    assert config.is_ignored("GHSA-aaaa-bbbb-cccc", on=dt.date(2026, 12, 31)) is True
    assert config.is_ignored("GHSA-aaaa-bbbb-cccc", on=dt.date(2027, 1, 1)) is False


def test_advisories_that_are_not_listed_are_never_ignored():
    config = parse_repo_config(MINIMAL, path=".vulnagent.yml")

    assert config.is_ignored("GHSA-aaaa-bbbb-cccc", on=dt.date(2026, 10, 21)) is False
