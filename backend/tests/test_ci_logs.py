from vulnagent.agent.ci_logs import (
    MAX_EXCERPT_BYTES,
    error_signature,
    extract_excerpt,
    referenced_repo_files,
)

NOISY_LOG = """2024-03-21T12:34:56.7890123Z ##[group]Run npm ci
2024-03-21T12:34:57.0000000Z npm ci
2024-03-21T12:35:10.1234567Z added 412 packages in 13s
2024-03-21T12:35:10.2000000Z ##[endgroup]
2024-03-21T12:35:11.0000000Z > test-app@1.0.0 test
2024-03-21T12:35:11.1000000Z > vitest run
2024-03-21T12:35:14.5000000Z  FAIL  src/auth.test.ts > signs a token
2024-03-21T12:35:14.5100000Z TypeError: jwt.sign is not a function
2024-03-21T12:35:14.5200000Z     at signToken (/home/runner/work/app/app/src/auth.ts:12:19)
2024-03-21T12:35:14.5300000Z     at Object.<anonymous> (/home/runner/work/app/app/src/auth.test.ts:8:20)
2024-03-21T12:35:14.6000000Z Tests  1 failed | 4 passed (5)
2024-03-21T12:35:15.0000000Z ##[error]Process completed with exit code 1.
"""


class TestExtractingTheRelevantLines:
    def test_keeps_the_failing_test_line(self):
        assert "FAIL  src/auth.test.ts" in extract_excerpt(NOISY_LOG)

    def test_keeps_the_error_itself(self):
        assert "TypeError: jwt.sign is not a function" in extract_excerpt(NOISY_LOG)

    def test_keeps_the_stack_frames(self):
        assert "at signToken" in extract_excerpt(NOISY_LOG)

    def test_drops_the_noise_around_the_failure(self):
        excerpt = extract_excerpt(NOISY_LOG)

        assert "added 412 packages" not in excerpt
        assert "##[group]" not in excerpt

    def test_strips_the_actions_timestamp_prefix(self):
        assert "2024-03-21T12:35:14" not in extract_excerpt(NOISY_LOG)

    def test_keeps_an_npm_error(self):
        log = "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree\n"

        assert "ERESOLVE" in extract_excerpt(log)

    def test_keeps_a_typescript_diagnostic(self):
        log = "src/auth.ts(12,19): error TS2339: Property 'sign' does not exist.\n"

        assert "TS2339" in extract_excerpt(log)

    def test_caps_the_excerpt_so_the_prompt_stays_affordable(self):
        log = "\n".join(f"Error: failure number {index}" for index in range(5000))

        assert len(extract_excerpt(log).encode()) <= MAX_EXCERPT_BYTES

    def test_keeps_the_last_errors_when_it_has_to_truncate(self):
        log = "\n".join(f"Error: failure number {index}" for index in range(5000))

        assert "failure number 4999" in extract_excerpt(log)

    def test_a_log_with_nothing_error_shaped_falls_back_to_its_tail(self):
        log = "\n".join(f"ordinary line {index}" for index in range(200))

        excerpt = extract_excerpt(log)

        assert "ordinary line 199" in excerpt

    def test_redacts_a_credential_that_leaked_into_the_log(self):
        log = "Error: auth failed with ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"

        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in extract_excerpt(log)


class TestErrorSignature:
    def test_two_runs_of_the_same_failure_share_a_signature(self):
        first = error_signature(extract_excerpt(NOISY_LOG))
        second = error_signature(
            extract_excerpt(NOISY_LOG.replace("12:35:14", "19:02:41").replace("app/app", "app/x"))
        )

        assert first == second

    def test_different_failures_have_different_signatures(self):
        other = NOISY_LOG.replace("jwt.sign is not a function", "jwt.verify is not a function")

        assert error_signature(NOISY_LOG) != error_signature(other)

    def test_drops_absolute_paths_but_keeps_the_repository_relative_part(self):
        signature = error_signature("at signToken (/home/runner/work/app/app/src/auth.ts:12:19)")

        assert "/home/runner" not in signature
        assert "src/auth.ts" in signature

    def test_drops_line_and_column_numbers(self):
        signature = error_signature("at x (src/auth.ts:12:19)")

        assert "12:19" not in signature

    def test_drops_hex_hashes(self):
        first = error_signature("failed at commit 3f2a1b9c4d5e6f708192a3b4c5d6e7f8a9b0c1d2")
        second = error_signature("failed at commit a1b2c3d4e5f60718293a4b5c6d7e8f9012345678")

        assert first == second

    def test_drops_timings_that_change_between_runs(self):
        first = error_signature("Tests failed in 1.23s")
        second = error_signature("Tests failed in 4.56s")

        assert first == second

    def test_drops_temporary_directory_names(self):
        first = error_signature("ENOENT: /tmp/vitest-7f3a9c/run.js")
        second = error_signature("ENOENT: /tmp/vitest-2b8e1d/run.js")

        assert first == second

    def test_keeps_the_signature_short_enough_to_embed(self):
        assert len(error_signature(NOISY_LOG)) <= 1000

    def test_an_empty_log_has_an_empty_signature(self):
        assert error_signature("") == ""


class TestFilesWorthSending:
    def test_finds_the_repository_files_named_in_the_failure(self):
        found = referenced_repo_files(extract_excerpt(NOISY_LOG))

        assert sorted(found) == ["src/auth.test.ts", "src/auth.ts"]

    def test_cuts_a_runner_absolute_path_back_to_its_repository_relative_part(self):
        excerpt = "at signToken (/home/runner/work/app/app/src/auth.ts:12:19)"

        assert referenced_repo_files(excerpt) == ["src/auth.ts"]

    def test_does_not_mistake_a_method_call_for_a_file(self):
        assert referenced_repo_files("TypeError: jwt.sign is not a function") == []

    def test_ignores_files_inside_node_modules(self):
        excerpt = "at x (/home/runner/work/app/app/node_modules/jsonwebtoken/index.js:1:1)"

        assert referenced_repo_files(excerpt) == []

    def test_ignores_paths_outside_the_checkout(self):
        assert referenced_repo_files("at node:internal/modules/cjs/loader:1:1") == []

    def test_finds_a_file_named_by_a_typescript_diagnostic(self):
        excerpt = "src/auth.ts(12,19): error TS2339: Property 'sign' does not exist."

        assert referenced_repo_files(excerpt) == ["src/auth.ts"]

    def test_lists_each_file_once_in_the_order_it_first_appeared(self):
        excerpt = "at a (src/b.ts:1:1)\nat c (src/a.ts:2:2)\nat d (src/b.ts:3:3)"

        assert referenced_repo_files(excerpt) == ["src/b.ts", "src/a.ts"]

    def test_caps_how_many_files_it_asks_for(self):
        excerpt = "\n".join(f"at f (src/file{index}.ts:1:1)" for index in range(20))

        assert len(referenced_repo_files(excerpt)) <= 5
