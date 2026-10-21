import pytest

from tests.helpers import npm_files


@pytest.fixture
def npm_fixture():
    return npm_files
