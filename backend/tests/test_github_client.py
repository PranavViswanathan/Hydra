import base64

import httpx
import pytest
import respx

from vulnagent.core.errors import VulnAgentError
from vulnagent.github.auth import GitHubAppAuth, app_jwt
from vulnagent.github.client import GitHubClient, Repository

API = "https://api.github.com"
REPO = Repository(owner="pranav", name="test-app")

# A throwaway key generated for the test suite only.
PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAuEI84e61CJUkt6yPqQxwj/Dokhq/QOSQ/7US9jVq4BDQjS0h
NstpfQesXi7YCEBEqlFW5QNYB413Jfp+FwT5sSr4SSFh8roAJHnD4Le9Y93QBNu9
SAmei+Wqgu4IOnXbqzmg4wIS3BSKaa/bKiopr9nLTZtKooVpNnmmxM7/1aItugnO
Jlw+N6g1+Rwh7Pwx0hMKnPwUUrCPXvCOBlZtVV+i3MjfKA7Hp7AJiSoaE0U1YDt9
UuN9VUgzJyEDB3PmKiPSpxVw1kODg7Tl+RG7j0LIYDopWZ18StMsDbPLDJzsjyPW
/Ag7eSZuYXzJvhnHfaWAAjvJAuiBBVm3KgkEVQIDAQABAoIBABc+tfcLufdp906b
nKkHKnkiO3jZGnkZjKhRo+F/Jis7u8+fmqHSwg1Vpztfff32e6Mf7U4pYJTdViNq
qTcGt+hPozB4n2ZzbBqt6NXj4Cbl3/0I6qVYn1GHSP5JAK09WpfMhp000QPGLJr+
JjA4zvcCCxmQhncfzQDkEnOgKJq+6lHr3tLwN9qcaCcJiBV8/ZtXH37fWNe71ZI4
MOzuM1zUG6jLcbxRwa/691pejzWRS3Z+Vc5atKTAtMu6qKAV+fy4McEyoMAsL8RM
umVxABNXxMtL+/dOsOiCZOqzV94ceJbI2iOzeM3dkFId2t2dzMJl2OxWbUl4alK9
QWvQvhkCgYEA+3hLbxn/21B5ZWUm/aLDV7X0OZ7BOvv0efXp8/tHlQ5pMF+FxeFy
q9SX5eQKYoZXMGUHYo2Ms9SmvcA7iQjXiaV9UGubDf3igM/l+HowHFmlDACmXeER
3ePprTSTrW/UOgApEhTTnFxElLsoC4NY6g+2KybqUJgWrpbwkv4cwdkCgYEAu5P8
Ks2QsruT8xDEOR7BJrQpEghOQa0aOCJlscfk02ZGjvKsVerzJbu+L+lmyqyk6ctB
OVGC4ST/kjsrWcD5c5KCQER9/LuxatliBboqHXf927zO34TBdTrFkH6YVnqJD5iy
PTQB7ROg0B11VzTbf2D9H6PQD8FlQxCMsrfrjN0CgYBSFCaTAep4HCEzjjuWx9x4
sYQgloe9h+V5NWICZ78qkMSWrGcOepKiMUbPG4qkM/Mbca5iZY9KVxuBjdAg30jy
vZhUenrmqzqWDsWiP8eaSUxMyZ2DwOXDBhQMm7+j+X9M2yaMp02WmKst3JSqhVmt
NCmilhYe7jVhERU+9UBPqQKBgEeqd4qm9WTEM/eG7WFhdaxi4ton4DZJe538zlvJ
Ioz+I3EUGHHPDUzaWQSXKRXANlW4uVe748Q/TYHCJ4LoLqZQUIFbacM4tsU6/q9v
fA28PXpJvcQ6RWuTo83cADnyIRGbZmXpy96XRDafOqix4jbdiHghLyoF2rlvxkG1
8UHlAoGBAKaPs53maJONV8FUVB1QpYlGSZgastVbtaie4yEUD19pRP2FyvGAluk8
sVWDvcpPQnAcuUj5OT31bjiNmJGdpTcGNWiLT0jrZCqwGarwzWuvfWOCRJppOfQT
0VScvV2m4bOxO5kkbOnGYbUiy7oPKZ+PbHp19kJp6uJwklJXJEf9
-----END RSA PRIVATE KEY-----"""


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield GitHubClient(token="ghs_test", http=http)


def contents(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


class TestAppAuthentication:
    def test_signs_a_jwt_the_app_can_authenticate_with(self):
        import jwt as pyjwt

        token = app_jwt(app_id=42, private_key=PRIVATE_KEY, now=1_700_000_000)
        claims = pyjwt.decode(token, options={"verify_signature": False})

        assert claims["iss"] == "42"
        assert claims["iat"] < claims["exp"]

    def test_the_jwt_stays_inside_githubs_ten_minute_limit(self):
        import jwt as pyjwt

        token = app_jwt(app_id=42, private_key=PRIVATE_KEY, now=1_700_000_000)
        claims = pyjwt.decode(token, options={"verify_signature": False})

        assert claims["exp"] - claims["iat"] <= 600

    @respx.mock
    def test_exchanges_the_jwt_for_an_installation_token(self):
        respx.post(f"{API}/app/installations/99/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )

        with httpx.Client() as http:
            auth = GitHubAppAuth(app_id=42, private_key=PRIVATE_KEY, http=http)

            assert auth.token_for(99) == "ghs_installation"

    @respx.mock
    def test_reuses_a_token_that_has_not_expired(self):
        route = respx.post(f"{API}/app/installations/99/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )

        with httpx.Client() as http:
            auth = GitHubAppAuth(app_id=42, private_key=PRIVATE_KEY, http=http)
            auth.token_for(99)
            auth.token_for(99)

        assert route.call_count == 1

    @respx.mock
    def test_mints_a_new_token_once_the_old_one_is_about_to_expire(self):
        route = respx.post(f"{API}/app/installations/99/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "ghs_x", "expires_at": "2000-01-01T00:00:00Z"}
            )
        )

        with httpx.Client() as http:
            auth = GitHubAppAuth(app_id=42, private_key=PRIVATE_KEY, http=http)
            auth.token_for(99)
            auth.token_for(99)

        assert route.call_count == 2

    @respx.mock
    def test_keeps_installations_apart(self):
        respx.post(f"{API}/app/installations/1/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "one", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )
        respx.post(f"{API}/app/installations/2/access_tokens").mock(
            return_value=httpx.Response(
                201, json={"token": "two", "expires_at": "2099-01-01T00:00:00Z"}
            )
        )

        with httpx.Client() as http:
            auth = GitHubAppAuth(app_id=42, private_key=PRIVATE_KEY, http=http)

            assert (auth.token_for(1), auth.token_for(2)) == ("one", "two")


class TestReadingFiles:
    @respx.mock
    def test_reads_a_file_at_a_ref(self, client):
        respx.get(f"{API}/repos/pranav/test-app/contents/package.json").mock(
            return_value=httpx.Response(200, json=contents('{"name": "test-app"}'))
        )

        assert client.get_file(REPO, "package.json", "main") == '{"name": "test-app"}'

    @respx.mock
    def test_a_missing_file_is_absent_rather_than_an_error(self, client):
        respx.get(f"{API}/repos/pranav/test-app/contents/nope.json").mock(
            return_value=httpx.Response(404)
        )

        assert client.get_file(REPO, "nope.json", "main") is None

    @respx.mock
    def test_fetching_several_files_skips_the_ones_that_are_missing(self, client):
        respx.get(f"{API}/repos/pranav/test-app/contents/package.json").mock(
            return_value=httpx.Response(200, json=contents("{}"))
        )
        respx.get(f"{API}/repos/pranav/test-app/contents/package-lock.json").mock(
            return_value=httpx.Response(404)
        )

        found = client.get_files(REPO, ["package.json", "package-lock.json"], "main")

        assert list(found) == ["package.json"]

    @respx.mock
    def test_lists_the_root_so_adapters_can_detect_the_ecosystem(self, client):
        respx.get(f"{API}/repos/pranav/test-app/contents").mock(
            return_value=httpx.Response(
                200, json=[{"name": "package.json"}, {"name": "src", "type": "dir"}]
            )
        )

        assert client.list_root_paths(REPO, "main") == ["package.json", "src"]

    @respx.mock
    def test_reads_the_head_of_a_branch(self, client):
        respx.get(f"{API}/repos/pranav/test-app/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
        )

        assert client.head_sha(REPO, "main") == "abc123"


class TestWritingCode:
    @respx.mock
    def test_creates_a_branch_from_a_commit(self, client):
        route = respx.post(f"{API}/repos/pranav/test-app/git/refs").mock(
            return_value=httpx.Response(201, json={})
        )

        client.create_branch(REPO, "vulnagent/run-1", "abc123")

        assert b"refs/heads/vulnagent/run-1" in route.calls.last.request.read()

    def test_refuses_to_create_a_branch_outside_its_own_namespace(self, client):
        with pytest.raises(VulnAgentError, match="main"):
            client.create_branch(REPO, "main", "abc123")

    def test_refuses_to_commit_to_the_default_branch(self, client):
        with pytest.raises(VulnAgentError):
            client.commit_files(
                REPO, branch="main", base_sha="abc", files={"a.ts": "x"}, message="m"
            )

    def test_refuses_to_create_an_empty_commit(self, client):
        with pytest.raises(VulnAgentError, match="empty"):
            client.commit_files(
                REPO, branch="vulnagent/run-1", base_sha="abc", files={}, message="m"
            )

    @respx.mock
    def test_writes_a_commit_through_the_git_data_api(self, client):
        respx.get(f"{API}/repos/pranav/test-app/git/commits/base1").mock(
            return_value=httpx.Response(200, json={"tree": {"sha": "tree-base"}})
        )
        tree_route = respx.post(f"{API}/repos/pranav/test-app/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree-new"})
        )
        respx.post(f"{API}/repos/pranav/test-app/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit-new"})
        )
        ref_route = respx.patch(f"{API}/repos/pranav/test-app/git/refs/heads/vulnagent/run-1").mock(
            return_value=httpx.Response(200, json={})
        )

        new_sha = client.commit_files(
            REPO,
            branch="vulnagent/run-1",
            base_sha="base1",
            files={"package.json": "{}"},
            message="fix(deps): resolve 1 vulnerability [vulnagent]",
        )

        assert new_sha == "commit-new"
        assert b"tree-base" in tree_route.calls.last.request.read()
        assert b"commit-new" in ref_route.calls.last.request.read()


class TestPullRequests:
    @respx.mock
    def test_opens_a_pull_request_from_the_agent_branch(self, client):
        route = respx.post(f"{API}/repos/pranav/test-app/pulls").mock(
            return_value=httpx.Response(201, json={"number": 7, "html_url": "https://pr/7"})
        )

        opened = client.open_pull_request(
            REPO, head="vulnagent/run-1", base="main", title="t", body="b"
        )

        assert opened["number"] == 7
        assert b"vulnagent/run-1" in route.calls.last.request.read()

    def test_refuses_to_open_a_pull_request_from_a_branch_it_does_not_own(self, client):
        with pytest.raises(VulnAgentError):
            client.open_pull_request(REPO, head="main", base="main", title="t", body="b")

    @respx.mock
    def test_updates_the_agent_log_section_of_the_body(self, client):
        route = respx.patch(f"{API}/repos/pranav/test-app/pulls/7").mock(
            return_value=httpx.Response(200, json={})
        )

        client.update_pull_request_body(REPO, 7, "new body")

        assert b"new body" in route.calls.last.request.read()

    @respx.mock
    def test_labels_the_pull_request(self, client):
        route = respx.post(f"{API}/repos/pranav/test-app/issues/7/labels").mock(
            return_value=httpx.Response(200, json=[])
        )

        client.add_labels(REPO, 7, ["vulnagent"])

        assert b"vulnagent" in route.calls.last.request.read()

    @respx.mock
    def test_squash_merges(self, client):
        route = respx.put(f"{API}/repos/pranav/test-app/pulls/7/merge").mock(
            return_value=httpx.Response(200, json={"merged": True})
        )

        client.merge_pull_request(REPO, 7)

        assert b"squash" in route.calls.last.request.read()


class TestChecks:
    def outcome_for(self, client, runs):
        with respx.mock:
            respx.get(f"{API}/repos/pranav/test-app/commits/sha1/check-runs").mock(
                return_value=httpx.Response(200, json={"check_runs": runs})
            )
            return client.check_outcome(REPO, "sha1")

    def test_all_green_passes(self, client):
        runs = [{"id": 1, "status": "completed", "conclusion": "success"}]

        outcome = self.outcome_for(client, runs)

        assert (outcome.all_completed, outcome.all_passed) == (True, True)

    def test_a_failure_is_reported_with_the_job_to_read_logs_from(self, client):
        runs = [
            {"id": 1, "status": "completed", "conclusion": "success"},
            {"id": 2, "status": "completed", "conclusion": "failure"},
        ]

        outcome = self.outcome_for(client, runs)

        assert outcome.all_passed is False
        assert outcome.failed_job_ids == [2]

    def test_a_run_still_going_is_not_complete(self, client):
        runs = [{"id": 1, "status": "in_progress"}]

        assert self.outcome_for(client, runs).all_completed is False

    def test_a_skipped_check_does_not_count_as_a_failure(self, client):
        runs = [{"id": 1, "status": "completed", "conclusion": "skipped"}]

        assert self.outcome_for(client, runs).all_passed is True

    def test_a_cancelled_check_counts_as_a_failure(self, client):
        runs = [{"id": 1, "status": "completed", "conclusion": "cancelled"}]

        assert self.outcome_for(client, runs).all_passed is False

    def test_a_repository_with_no_checks_at_all_counts_as_passing(self, client):
        assert self.outcome_for(client, []).all_passed is True

    @respx.mock
    def test_downloads_a_job_log(self, client):
        respx.get(f"{API}/repos/pranav/test-app/actions/jobs/5/logs").mock(
            return_value=httpx.Response(200, text="FAIL src/auth.test.ts")
        )

        assert "FAIL" in client.job_log(REPO, 5)

    @respx.mock
    def test_a_log_that_has_expired_reads_as_empty(self, client):
        respx.get(f"{API}/repos/pranav/test-app/actions/jobs/5/logs").mock(
            return_value=httpx.Response(404)
        )

        assert client.job_log(REPO, 5) == ""


class TestRepositoryNames:
    def test_splits_a_full_name(self):
        assert Repository.from_full_name("pranav/test-app") == REPO

    @pytest.mark.parametrize("bad", ["test-app", "", "/test-app", "pranav/"])
    def test_rejects_something_that_is_not_a_full_name(self, bad):
        with pytest.raises(VulnAgentError):
            Repository.from_full_name(bad)
