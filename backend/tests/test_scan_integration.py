"""scan_repo end to end against recorded GitHub and OSV responses (§19)."""

import base64
import datetime as dt
import json

import httpx
import pytest
import respx

from tests.fakes import FakeTablesDB
from tests.helpers import npm_files
from vulnagent.db.repositories import Database
from vulnagent.db.rows import Repo
from vulnagent.github.client import GitHubClient
from vulnagent.osv.client import OsvClient
from vulnagent.scanning.scan import RepoScanner

API = "https://api.github.com"
OSV = "https://api.osv.dev"
NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)

FIXTURE = npm_files("v3-nested")

LODASH_ADVISORY = {
    "id": "GHSA-qs",
    "aliases": ["CVE-2022-24999"],
    "summary": "Prototype pollution in qs",
    "database_specific": {"severity": "HIGH"},
    "affected": [
        {
            "package": {"name": "qs", "ecosystem": "npm"},
            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "6.5.3"}]}],
        }
    ],
}


def contents(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


@pytest.fixture
def tables():
    return FakeTablesDB()


@pytest.fixture
def db(tables):
    return Database(tables)


@pytest.fixture
def repo(db):
    return db.repos.create(
        Repo(
            installation_id="inst1",
            github_repo_id=1,
            full_name="pranav/test-app",
            default_branch="main",
            owner_user_id="user1",
            has_config=True,
            config_json="version: 1\n",
        )
    )


def mock_github() -> None:
    respx.get(f"{API}/repos/pranav/test-app/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "head1"}})
    )
    respx.get(f"{API}/repos/pranav/test-app/contents").mock(
        return_value=httpx.Response(
            200, json=[{"name": "package.json"}, {"name": "package-lock.json"}]
        )
    )
    for path, text in FIXTURE.items():
        respx.get(f"{API}/repos/pranav/test-app/contents/{path}").mock(
            return_value=httpx.Response(200, json=contents(text))
        )


def mock_osv(vulnerable_purl: str = "qs@6.5.2") -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        queries = json.loads(request.content)["queries"]
        results = [
            {"vulns": [{"id": "GHSA-qs"}]}
            if f"{query['package']['name']}@{query['version']}" == vulnerable_purl
            else {}
            for query in queries
        ]
        return httpx.Response(200, json={"results": results})

    respx.post(f"{OSV}/v1/querybatch").mock(side_effect=respond)
    respx.get(f"{OSV}/v1/vulns/GHSA-qs").mock(
        return_value=httpx.Response(200, json=LODASH_ADVISORY)
    )


def scan(db, repo, trigger="manual"):
    with httpx.Client() as http:
        scanner = RepoScanner(
            db=db,
            github=GitHubClient(token="t", http=http),
            osv=OsvClient(base_url=OSV, http=http),
            now=NOW,
        )
        return scanner.scan(repo, trigger=trigger)


class TestASuccessfulScan:
    @respx.mock
    def test_records_every_installed_package(self, db, repo):
        mock_github()
        mock_osv()

        result = scan(db, repo)

        assert result.packages_scanned == len(db.packages.for_repo(repo.id))
        assert result.packages_scanned == 6

    @respx.mock
    def test_finds_the_vulnerable_package(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        found = db.vulnerabilities.for_repo(repo.id)
        assert [(row.package_name, row.installed_version) for row in found] == [("qs", "6.5.2")]

    @respx.mock
    def test_reads_the_fixed_version_from_the_advisory(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        assert db.vulnerabilities.for_repo(repo.id)[0].fixed_version == "6.5.3"

    @respx.mock
    def test_carries_the_severity_through_from_the_advisory(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        assert db.vulnerabilities.for_repo(repo.id)[0].severity == "high"

    @respx.mock
    def test_marks_a_nested_package_as_transitive(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        assert db.vulnerabilities.for_repo(repo.id)[0].is_direct is False

    @respx.mock
    def test_a_transitive_vulnerability_traces_back_to_root_through_the_edges(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        edges = db.edges.for_repo(repo.id)
        by_child = {edge.child_purl: edge.parent_purl for edge in edges}
        assert by_child["pkg:npm/qs@6.5.2"] == "pkg:npm/express@4.16.0"
        assert by_child["pkg:npm/express@4.16.0"] == "ROOT"

    @respx.mock
    def test_updates_the_severity_counts_on_the_repository(self, db, repo):
        mock_github()
        mock_osv()

        result = scan(db, repo)

        assert result.counts["high"] == 1
        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.open_high == 1

    @respx.mock
    def test_caches_the_advisory_so_the_next_scan_need_not_refetch_it(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        assert db.advisories.by_osv_id("GHSA-qs") is not None

    @respx.mock
    def test_records_the_scan_as_succeeded(self, db, repo):
        mock_github()
        mock_osv()

        result = scan(db, repo)

        recorded = db.scans.get(result.scan_id)
        assert recorded is not None
        assert recorded.status == "succeeded"
        assert recorded.vulns_found == 1

    @respx.mock
    def test_notes_when_the_repository_was_last_scanned(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.last_scan_at == NOW


class TestRescanning:
    @respx.mock
    def test_a_second_scan_does_not_duplicate_the_vulnerability(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)
        scan(db, repo)

        assert len(db.vulnerabilities.for_repo(repo.id)) == 1

    @respx.mock
    def test_a_vulnerability_that_disappears_is_marked_fixed(self, db, repo):
        mock_github()
        mock_osv()
        scan(db, repo)

        respx.post(f"{OSV}/v1/querybatch").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={"results": [{} for _ in json.loads(request.content)["queries"]]},
            )
        )
        scan(db, repo)

        assert db.vulnerabilities.for_repo(repo.id)[0].status == "fixed"

    @respx.mock
    def test_the_counts_drop_once_it_is_fixed(self, db, repo):
        mock_github()
        mock_osv()
        scan(db, repo)

        respx.post(f"{OSV}/v1/querybatch").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={"results": [{} for _ in json.loads(request.content)["queries"]]},
            )
        )
        result = scan(db, repo)

        assert result.counts["high"] == 0

    @respx.mock
    def test_the_package_snapshot_is_replaced_rather_than_appended_to(self, db, repo):
        mock_github()
        mock_osv()

        scan(db, repo)
        scan(db, repo)

        assert len(db.packages.for_repo(repo.id)) == 6


class TestIgnoreRules:
    @respx.mock
    def test_an_ignored_advisory_is_recorded_but_not_counted(self, db, tables, repo):
        mock_github()
        mock_osv()
        db.repos.update(
            repo.id,
            {
                "config_json": (
                    "version: 1\nagent:\n  ignore:\n"
                    "    - id: GHSA-qs\n      reason: not reachable\n"
                )
            },
        )
        reloaded = db.repos.get(repo.id)
        assert reloaded is not None

        result = scan(db, reloaded)

        assert db.vulnerabilities.for_repo(repo.id)[0].status == "ignored"
        assert result.counts["high"] == 0


class TestFailures:
    @respx.mock
    def test_a_repository_with_no_supported_ecosystem_fails_the_scan(self, db, repo):
        respx.get(f"{API}/repos/pranav/test-app/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "head1"}})
        )
        respx.get(f"{API}/repos/pranav/test-app/contents").mock(
            return_value=httpx.Response(200, json=[{"name": "pom.xml"}])
        )

        with pytest.raises(Exception, match="no supported ecosystem"):
            scan(db, repo)

    @respx.mock
    def test_a_failed_scan_is_recorded_with_its_error(self, db, repo):
        respx.get(f"{API}/repos/pranav/test-app/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "head1"}})
        )
        respx.get(f"{API}/repos/pranav/test-app/contents").mock(
            return_value=httpx.Response(200, json=[{"name": "pom.xml"}])
        )

        with pytest.raises(Exception, match="no supported ecosystem"):
            scan(db, repo)

        [recorded] = db.scans.find([])
        assert recorded.status == "failed"
        assert "no supported ecosystem" in (recorded.error or "")
