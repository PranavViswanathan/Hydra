import httpx
import pytest
import respx

from vulnagent.osv.client import OsvClient, PackageQuery
from vulnagent.osv.models import advisory_from_osv

BASE = "https://api.osv.dev"


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield OsvClient(base_url=BASE, http=http)


def a_query(name="lodash", version="4.17.20") -> PackageQuery:
    return PackageQuery(name=name, ecosystem="npm", version=version)


class TestQueryBatch:
    @respx.mock
    def test_returns_the_advisory_ids_affecting_each_package(self, client):
        respx.post(f"{BASE}/v1/querybatch").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"vulns": [{"id": "GHSA-29mw-wpgm-hmr9"}, {"id": "GHSA-p6mc-m468-83gg"}]},
                        {"vulns": [{"id": "GHSA-hrpp-h998-j3pp"}]},
                    ]
                },
            )
        )

        found = client.query_batch([a_query("lodash"), a_query("qs", "6.5.2")])

        assert found == {
            "pkg:npm/lodash@4.17.20": ["GHSA-29mw-wpgm-hmr9", "GHSA-p6mc-m468-83gg"],
            "pkg:npm/qs@6.5.2": ["GHSA-hrpp-h998-j3pp"],
        }

    @respx.mock
    def test_sends_each_package_in_the_shape_osv_expects(self, client):
        route = respx.post(f"{BASE}/v1/querybatch").mock(
            return_value=httpx.Response(200, json={"results": [{}]})
        )

        client.query_batch([a_query()])

        assert (
            route.calls.last.request.read()
            == httpx.Request(
                "POST",
                f"{BASE}/v1/querybatch",
                json={
                    "queries": [
                        {"package": {"name": "lodash", "ecosystem": "npm"}, "version": "4.17.20"}
                    ]
                },
            ).read()
        )

    @respx.mock
    def test_omits_packages_that_have_no_advisories(self, client):
        respx.post(f"{BASE}/v1/querybatch").mock(
            return_value=httpx.Response(200, json={"results": [{}, {"vulns": [{"id": "GHSA-x"}]}]})
        )

        found = client.query_batch([a_query("clean"), a_query("dirty")])

        assert found == {"pkg:npm/dirty@4.17.20": ["GHSA-x"]}

    @respx.mock
    def test_splits_large_scans_into_batches_osv_will_accept(self, client):
        route = respx.post(f"{BASE}/v1/querybatch").mock(
            side_effect=lambda request: httpx.Response(
                200, json={"results": [{} for _ in request.read().decode().split('"package"')[1:]]}
            )
        )

        client.query_batch([a_query(f"pkg{index}") for index in range(2500)])

        assert route.call_count == 3

    def test_an_empty_scan_does_not_call_the_api_at_all(self, client):
        with respx.mock:
            route = respx.post(f"{BASE}/v1/querybatch")

            assert client.query_batch([]) == {}
            assert route.call_count == 0

    @respx.mock
    def test_a_result_list_shorter_than_the_query_list_is_tolerated(self, client):
        respx.post(f"{BASE}/v1/querybatch").mock(
            return_value=httpx.Response(200, json={"results": [{"vulns": [{"id": "GHSA-x"}]}]})
        )

        found = client.query_batch([a_query("a"), a_query("b")])

        assert found == {"pkg:npm/a@4.17.20": ["GHSA-x"]}

    @respx.mock
    def test_raises_when_osv_returns_an_error(self, client):
        respx.post(f"{BASE}/v1/querybatch").mock(return_value=httpx.Response(500, text="boom"))

        with pytest.raises(httpx.HTTPStatusError):
            client.query_batch([a_query()])


class TestGetVulnerability:
    @respx.mock
    def test_fetches_one_advisory_by_id(self, client):
        respx.get(f"{BASE}/v1/vulns/GHSA-29mw-wpgm-hmr9").mock(
            return_value=httpx.Response(200, json={"id": "GHSA-29mw-wpgm-hmr9", "summary": "ReDoS"})
        )

        assert client.get_vulnerability("GHSA-29mw-wpgm-hmr9")["summary"] == "ReDoS"

    @respx.mock
    def test_returns_nothing_when_an_advisory_has_been_withdrawn(self, client):
        respx.get(f"{BASE}/v1/vulns/GHSA-gone").mock(return_value=httpx.Response(404))

        assert client.get_vulnerability("GHSA-gone") is None


class TestNormalisingAnAdvisory:
    def test_maps_an_osv_record_onto_the_advisory_row(self):
        advisory = advisory_from_osv(
            {
                "id": "GHSA-29mw-wpgm-hmr9",
                "aliases": ["CVE-2020-8203"],
                "summary": "Prototype pollution in lodash",
                "details": "Long description.",
                "modified": "2023-11-08T04:03:49.567Z",
                "severity": [
                    {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}
                ],
                "affected": [{"package": {"name": "lodash", "ecosystem": "npm"}}],
            }
        )

        assert advisory.osv_id == "GHSA-29mw-wpgm-hmr9"
        assert advisory.aliases == ["CVE-2020-8203"]
        assert advisory.summary == "Prototype pollution in lodash"
        assert advisory.severity == "critical"
        assert advisory.cvss_score == pytest.approx(9.8)

    def test_keeps_the_raw_affected_section_so_planning_can_reread_it(self):
        affected = [{"package": {"name": "lodash", "ecosystem": "npm"}}]

        advisory = advisory_from_osv({"id": "GHSA-x", "affected": affected})

        assert advisory.affected == affected

    def test_an_advisory_without_optional_fields_still_maps(self):
        advisory = advisory_from_osv({"id": "GHSA-x"})

        assert (advisory.aliases, advisory.summary, advisory.cvss_score) == ([], "", None)
        assert advisory.severity == "unknown"

    def test_reads_the_modified_timestamp_so_the_cache_can_be_refreshed(self):
        advisory = advisory_from_osv({"id": "GHSA-x", "modified": "2023-11-08T04:03:49.567Z"})

        assert advisory.osv_modified is not None
        assert advisory.osv_modified.year == 2023

    def test_a_missing_modified_timestamp_is_not_fatal(self):
        assert advisory_from_osv({"id": "GHSA-x"}).osv_modified is None
