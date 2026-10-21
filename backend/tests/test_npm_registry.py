import httpx
import pytest
import respx

from vulnagent.adapters.npm.registry import NpmRegistryClient

BASE = "https://registry.npmjs.org"


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield NpmRegistryClient(base_url=BASE, http=http)


def packument(**versions) -> dict:
    return {"name": "express", "versions": dict(versions)}


class TestListVersions:
    @respx.mock
    def test_lists_the_published_versions_lowest_first(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(
                200, json=packument(**{"4.17.1": {}, "4.16.0": {}, "4.9.0": {}})
            )
        )

        assert client.list_versions("express") == ["4.9.0", "4.16.0", "4.17.1"]

    @respx.mock
    def test_url_encodes_the_slash_in_a_scoped_package_name(self, client):
        route = respx.get(f"{BASE}/@babel%2Fcore").mock(
            return_value=httpx.Response(200, json=packument(**{"7.24.0": {}}))
        )

        assert client.list_versions("@babel/core") == ["7.24.0"]
        assert route.called

    @respx.mock
    def test_discards_versions_npm_would_not_accept(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(200, json=packument(**{"4.17.1": {}, "garbage": {}}))
        )

        assert client.list_versions("express") == ["4.17.1"]

    @respx.mock
    def test_an_unpublished_package_has_no_versions(self, client):
        respx.get(f"{BASE}/ghost").mock(return_value=httpx.Response(404))

        assert client.list_versions("ghost") == []

    @respx.mock
    def test_raises_when_the_registry_itself_is_broken(self, client):
        respx.get(f"{BASE}/express").mock(return_value=httpx.Response(503))

        with pytest.raises(httpx.HTTPStatusError):
            client.list_versions("express")


class TestGetDependencies:
    @respx.mock
    def test_returns_the_runtime_dependencies_of_one_version(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(
                200,
                json=packument(
                    **{"4.17.1": {"dependencies": {"qs": "6.7.0", "accepts": "~1.3.7"}}}
                ),
            )
        )

        assert client.get_dependencies("express", "4.17.1") == {"qs": "6.7.0", "accepts": "~1.3.7"}

    @respx.mock
    def test_a_version_with_no_dependencies_returns_nothing(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(200, json=packument(**{"4.17.1": {}}))
        )

        assert client.get_dependencies("express", "4.17.1") == {}

    @respx.mock
    def test_an_unknown_version_returns_nothing(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(200, json=packument(**{"4.17.1": {}}))
        )

        assert client.get_dependencies("express", "9.9.9") == {}

    @respx.mock
    def test_ignores_dev_dependencies_which_are_never_installed_transitively(self, client):
        respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(
                200,
                json=packument(
                    **{
                        "4.17.1": {
                            "dependencies": {"qs": "6.7.0"},
                            "devDependencies": {"mocha": "*"},
                        }
                    }
                ),
            )
        )

        assert client.get_dependencies("express", "4.17.1") == {"qs": "6.7.0"}


class TestCaching:
    @respx.mock
    def test_fetches_a_package_document_only_once(self, client):
        route = respx.get(f"{BASE}/express").mock(
            return_value=httpx.Response(
                200, json=packument(**{"4.17.1": {"dependencies": {"qs": "6.7.0"}}})
            )
        )

        client.list_versions("express")
        client.get_dependencies("express", "4.17.1")
        client.list_versions("express")

        assert route.call_count == 1

    @respx.mock
    def test_remembers_that_a_package_does_not_exist(self, client):
        route = respx.get(f"{BASE}/ghost").mock(return_value=httpx.Response(404))

        client.list_versions("ghost")
        client.list_versions("ghost")

        assert route.call_count == 1
