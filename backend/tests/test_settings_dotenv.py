import pytest

from vulnagent.config.settings import load_settings
from vulnagent.core.errors import ConfigError

DOTENV = """
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=from_file
APPWRITE_API_KEY=key
GITHUB_APP_ID=7
GITHUB_APP_PRIVATE_KEY=pem
GITHUB_WEBHOOK_SECRET=whsec
"""

REQUIRED_NAMES = (
    "APPWRITE_ENDPOINT",
    "APPWRITE_PROJECT_ID",
    "APPWRITE_API_KEY",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_WEBHOOK_SECRET",
)


@pytest.fixture(autouse=True)
def _clear_environment(monkeypatch):
    for name in REQUIRED_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_a_dotenv_file_is_ignored_unless_a_caller_asks_for_it(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(DOTENV)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError):
        load_settings()


def test_a_script_can_opt_into_reading_a_dotenv_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV)

    settings = load_settings(dotenv=str(env_file))

    assert settings.appwrite_project_id == "from_file"


def test_the_real_environment_wins_over_the_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(DOTENV)
    monkeypatch.setenv("APPWRITE_PROJECT_ID", "from_environment")

    settings = load_settings(dotenv=str(env_file))

    assert settings.appwrite_project_id == "from_environment"
