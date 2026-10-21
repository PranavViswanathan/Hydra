import pytest

from vulnagent.config.settings import Settings, load_settings
from vulnagent.core.errors import ConfigError

REQUIRED = {
    "APPWRITE_ENDPOINT": "https://cloud.appwrite.io/v1",
    "APPWRITE_PROJECT_ID": "proj_123",
    "APPWRITE_API_KEY": "key_secret",
    "GITHUB_APP_ID": "1234",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    "GITHUB_WEBHOOK_SECRET": "whsec",
}

PEM_ONE_LINE = "-----BEGIN RSA PRIVATE KEY-----\\nabc\\ndef\\n-----END RSA PRIVATE KEY-----"


def given_env(monkeypatch, **overrides: str | None):
    for name in (*REQUIRED, *overrides):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**REQUIRED, **overrides}.items():
        if value is not None:
            monkeypatch.setenv(name, value)


def test_reads_the_required_variables_from_the_environment(monkeypatch):
    given_env(monkeypatch)

    settings = load_settings()

    assert settings.appwrite_project_id == "proj_123"
    assert settings.github_app_id == 1234


def test_osv_base_url_falls_back_to_the_public_api(monkeypatch):
    given_env(monkeypatch)

    assert load_settings().osv_base_url == "https://api.osv.dev"


def test_osv_base_url_can_be_pointed_at_a_mirror(monkeypatch):
    given_env(monkeypatch, OSV_BASE_URL="http://localhost:8080")

    assert load_settings().osv_base_url == "http://localhost:8080"


def test_a_trailing_slash_on_osv_base_url_does_not_produce_double_slashed_requests(monkeypatch):
    given_env(monkeypatch, OSV_BASE_URL="https://api.osv.dev/")

    assert load_settings().osv_base_url == "https://api.osv.dev"


def test_a_private_key_pasted_with_escaped_newlines_is_turned_into_a_real_pem(monkeypatch):
    given_env(monkeypatch, GITHUB_APP_PRIVATE_KEY=PEM_ONE_LINE)

    pem = load_settings().github_app_private_key.get_secret_value()

    assert "\\n" not in pem
    assert pem.splitlines()[0] == "-----BEGIN RSA PRIVATE KEY-----"
    assert pem.splitlines()[-1] == "-----END RSA PRIVATE KEY-----"


def test_a_private_key_that_already_has_real_newlines_is_left_alone(monkeypatch):
    given_env(monkeypatch)

    pem = load_settings().github_app_private_key.get_secret_value()

    assert pem == REQUIRED["GITHUB_APP_PRIVATE_KEY"]


def test_secrets_do_not_leak_when_settings_are_printed_or_logged(monkeypatch):
    given_env(monkeypatch)

    rendered = repr(load_settings())

    assert "key_secret" not in rendered
    assert "whsec" not in rendered
    assert "BEGIN RSA PRIVATE KEY" not in rendered


def test_a_missing_required_variable_is_reported_by_name(monkeypatch):
    given_env(monkeypatch, APPWRITE_API_KEY=None)

    with pytest.raises(ConfigError, match="APPWRITE_API_KEY"):
        load_settings()


def test_llm_settings_are_optional_so_scan_only_deployments_still_boot(monkeypatch):
    given_env(monkeypatch)

    settings = load_settings()

    assert settings.llm_api_key is None
    assert settings.embedding_dim is None


def test_asking_for_llm_settings_that_were_never_configured_fails_loudly(monkeypatch):
    given_env(monkeypatch)

    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_settings().require_llm()


def test_llm_settings_are_returned_once_both_the_key_and_the_model_are_set(monkeypatch):
    given_env(monkeypatch, LLM_API_KEY="sk-test", LLM_MODEL="claude-opus-5")

    api_key, model = load_settings().require_llm()

    assert (api_key.get_secret_value(), model) == ("sk-test", "claude-opus-5")


def test_embedding_dimension_is_read_as_a_number(monkeypatch):
    given_env(monkeypatch, EMBEDDING_API_KEY="emb", EMBEDDING_MODEL="embed-1", EMBEDDING_DIM="1536")

    assert load_settings().embedding_dim == 1536


def test_a_non_numeric_embedding_dimension_is_reported_by_name(monkeypatch):
    given_env(monkeypatch, EMBEDDING_DIM="many")

    with pytest.raises(ConfigError, match="EMBEDDING_DIM"):
        load_settings()


def test_unrelated_environment_variables_are_ignored(monkeypatch):
    given_env(monkeypatch)
    monkeypatch.setenv("SOME_UNRELATED_THING", "x")

    assert isinstance(load_settings(), Settings)
