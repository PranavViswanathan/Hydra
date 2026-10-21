"""Every rule in §11 that can be enforced in code has a test here."""

import pytest

from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.safety import (
    MAX_CHANGED_FILES,
    MAX_CHANGED_LINES,
    MAX_RETRY_CEILING,
    SafetyReport,
    capped_retries,
    is_agent_branch,
    redact_secrets,
    review_edits,
    verify_webhook_signature,
)

SECRET = b"whsec_test"


def edit(path="src/auth.ts", search="const a = 1", replace="const a = 2") -> dict:
    return {"path": path, "search": search, "replace": replace}


def review(*edits, adapter=None) -> SafetyReport:
    return review_edits(list(edits), adapter=adapter or NpmAdapter())


class TestRuleOneNeverPushToTheDefaultBranch:
    @pytest.mark.parametrize("branch", ["vulnagent/abc123", "vulnagent/run-1"])
    def test_accepts_branches_the_agent_created(self, branch):
        assert is_agent_branch(branch) is True

    @pytest.mark.parametrize("branch", ["main", "master", "develop", "release/1.0"])
    def test_refuses_any_branch_the_agent_did_not_create(self, branch):
        assert is_agent_branch(branch) is False

    def test_refuses_a_branch_that_only_looks_like_an_agent_branch(self):
        assert is_agent_branch("not-vulnagent/abc") is False

    def test_refuses_a_branch_that_tries_to_escape_the_prefix(self):
        assert is_agent_branch("vulnagent/../main") is False


class TestRuleTwoProtectedPaths:
    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
            ".vulnagent.yml",
            ".vulnagent.json",
            "package.json",
            "package-lock.json",
        ],
    )
    def test_refuses_an_edit_to_a_file_the_agent_owns(self, path):
        report = review(edit(path=path))

        assert report.ok is False
        assert path in report.reason

    def test_allows_an_edit_to_ordinary_application_code(self):
        assert review(edit(path="src/auth.ts")).ok is True

    def test_allows_an_edit_to_a_test_file(self):
        assert review(edit(path="src/auth.test.ts")).ok is True

    @pytest.mark.parametrize("path", ["../outside.ts", "/etc/passwd", "src/../../escape.ts"])
    def test_refuses_a_path_that_leaves_the_repository(self, path):
        assert review(edit(path=path)).ok is False

    def test_refuses_an_edit_to_the_lockfile_of_a_different_ecosystem_adapter(self):
        assert review(edit(path="package-lock.json")).ok is False


class TestRuleThreeTestsMayNotBeWeakened:
    @pytest.mark.parametrize(
        "replacement",
        [
            "it.skip('works', () => {})",
            "describe.skip('suite', () => {})",
            "test.only('works', () => {})",
            "xit('works', () => {})",
            "// @ts-ignore\nconst a = 2",
            "// eslint-disable-next-line\nconst a = 2",
            "/* eslint-disable */",
        ],
    )
    def test_refuses_an_edit_that_disables_a_check(self, replacement):
        assert review(edit(replace=replacement)).ok is False

    def test_refuses_an_edit_that_deletes_a_test_case(self):
        report = review(
            edit(
                search="it('rejects an expired token', () => {\n  expect(1).toBe(1)\n})", replace=""
            )
        )

        assert report.ok is False
        assert "test" in report.reason.lower()

    def test_refuses_an_edit_that_deletes_a_whole_suite(self):
        report = review(edit(search="describe('auth', () => {})", replace=""))

        assert report.ok is False

    def test_allows_an_edit_that_updates_a_test_without_removing_it(self):
        report = review(
            edit(
                search="it('signs a token', () => { sign(payload) })",
                replace="it('signs a token', async () => { await sign(payload) })",
            )
        )

        assert report.ok is True

    def test_allows_adding_a_test(self):
        report = review(edit(search="const a = 1", replace="const a = 1\nit('new', () => {})"))

        assert report.ok is True

    def test_allows_the_word_test_inside_ordinary_code(self):
        assert review(edit(replace="const tested = latest")).ok is True


class TestRuleFourDiffCap:
    def test_allows_a_change_within_the_caps(self):
        assert review(edit(replace="\n".join(["line"] * 10))).ok is True

    def test_refuses_a_change_that_rewrites_too_many_lines(self):
        report = review(edit(replace="\n".join(["line"] * (MAX_CHANGED_LINES + 1))))

        assert report.ok is False
        assert str(MAX_CHANGED_LINES) in report.reason

    def test_counts_lines_across_every_edit_rather_than_one_at_a_time(self):
        half = "\n".join(["line"] * (MAX_CHANGED_LINES // 2 + 1))

        report = review(edit(path="a.ts", replace=half), edit(path="b.ts", replace=half))

        assert report.ok is False

    def test_refuses_a_change_that_touches_too_many_files(self):
        edits = [edit(path=f"src/file{index}.ts") for index in range(MAX_CHANGED_FILES + 1)]

        report = review(*edits)

        assert report.ok is False
        assert str(MAX_CHANGED_FILES) in report.reason

    def test_counts_one_file_once_even_when_edited_repeatedly(self):
        edits = [
            edit(path="src/one.ts", search=f"const a{i} = 1", replace=f"const a{i} = 2")
            for i in range(MAX_CHANGED_FILES + 2)
        ]

        assert review(*edits).ok is True


class TestRuleSixNoSecretsReachTheModel:
    def test_redacts_a_github_token(self):
        redacted = redact_secrets("using ghp_abcdefghijklmnopqrstuvwxyz0123456789 to auth")

        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
        assert "[redacted]" in redacted

    @pytest.mark.parametrize(
        "secret",
        [
            "ghs_abcdefghijklmnopqrstuvwxyz0123456789",
            "github_pat_11ABCDEFG0abcdefghijkl_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN RSA PRIVATE KEY-----",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc",
        ],
    )
    def test_redacts_other_credential_shapes(self, secret):
        assert secret not in redact_secrets(f"log line with {secret} in it")

    def test_redacts_an_environment_assignment_that_looks_like_a_secret(self):
        redacted = redact_secrets("GITHUB_TOKEN=abcdef123456789012345678")

        assert "abcdef123456789012345678" not in redacted

    def test_leaves_ordinary_log_output_alone(self):
        line = "FAIL src/auth.test.ts > signs a token"

        assert redact_secrets(line) == line


class TestRuleSevenRetryCeiling:
    @pytest.mark.parametrize(("configured", "expected"), [(0, 0), (3, 3), (5, 5)])
    def test_honours_a_retry_count_within_the_ceiling(self, configured, expected):
        assert capped_retries(configured) == expected

    def test_clamps_a_retry_count_above_the_ceiling(self):
        assert capped_retries(99) == MAX_RETRY_CEILING

    def test_treats_a_negative_retry_count_as_none(self):
        assert capped_retries(-1) == 0


class TestRuleNineWebhookSignature:
    def test_accepts_a_correctly_signed_delivery(self):
        body = b'{"action":"opened"}'
        signature = "sha256=1ba91d4d5b0b0e2b0a9a7bbd8c3a5c4f5bd1cdd0b6e65b1b2b0e2bb0c0e7a6f3"

        assert verify_webhook_signature(body, _sign(body), SECRET) is True
        assert verify_webhook_signature(body, signature, SECRET) is False

    def test_rejects_a_delivery_whose_body_was_tampered_with(self):
        signature = _sign(b'{"action":"opened"}')

        assert verify_webhook_signature(b'{"action":"closed"}', signature, SECRET) is False

    def test_rejects_a_delivery_signed_with_the_wrong_secret(self):
        body = b'{"action":"opened"}'

        assert verify_webhook_signature(body, _sign(body, b"other"), SECRET) is False

    def test_rejects_a_missing_signature(self):
        assert verify_webhook_signature(b"{}", None, SECRET) is False

    def test_rejects_a_signature_in_an_algorithm_we_do_not_accept(self):
        assert verify_webhook_signature(b"{}", "sha1=abc", SECRET) is False

    def test_rejects_a_malformed_signature_header(self):
        assert verify_webhook_signature(b"{}", "not-a-signature", SECRET) is False


def _sign(body: bytes, secret: bytes = SECRET) -> str:
    import hashlib
    import hmac

    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
