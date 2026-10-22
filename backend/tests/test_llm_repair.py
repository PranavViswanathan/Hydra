import json

import pytest

from vulnagent.core.errors import VulnAgentError
from vulnagent.llm.prompts.repair import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from vulnagent.llm.schemas import RepairResponse, parse_repair_response

VALID = {
    "analysis": "jsonwebtoken 9 requires a callback or returns a promise.",
    "edits": [{"path": "src/auth.ts", "search": "jwt.sign(p)", "replace": "await jwt.sign(p)"}],
    "confidence": 0.8,
    "give_up": False,
    "give_up_reason": None,
}


class TestParsingTheModelResponse:
    def test_reads_a_plain_json_response(self):
        response = parse_repair_response(json.dumps(VALID))

        assert response.analysis.startswith("jsonwebtoken 9")
        assert response.edits[0].path == "src/auth.ts"

    def test_strips_a_markdown_fence_the_model_added(self):
        response = parse_repair_response(f"```json\n{json.dumps(VALID)}\n```")

        assert response.edits[0].replace == "await jwt.sign(p)"

    def test_strips_a_fence_with_no_language_tag(self):
        response = parse_repair_response(f"```\n{json.dumps(VALID)}\n```")

        assert response.confidence == pytest.approx(0.8)

    def test_ignores_prose_the_model_wrapped_around_the_json(self):
        response = parse_repair_response(f"Here is the fix:\n{json.dumps(VALID)}\nHope that helps.")

        assert response.edits[0].path == "src/auth.ts"

    def test_a_response_that_gives_up_carries_its_reason(self):
        response = parse_repair_response(
            json.dumps(
                {
                    "analysis": "The failure is unrelated to the upgrade.",
                    "edits": [],
                    "confidence": 0.1,
                    "give_up": True,
                    "give_up_reason": "Pre-existing flaky test",
                }
            )
        )

        assert response.give_up is True
        assert response.give_up_reason == "Pre-existing flaky test"

    def test_defaults_the_optional_fields(self):
        response = parse_repair_response(json.dumps({"analysis": "x", "edits": []}))

        assert (response.confidence, response.give_up, response.give_up_reason) == (
            0.0,
            False,
            None,
        )

    def test_rejects_a_response_that_is_not_json_at_all(self):
        with pytest.raises(VulnAgentError, match="JSON"):
            parse_repair_response("I could not work out the fix, sorry.")

    def test_rejects_a_response_missing_the_analysis(self):
        with pytest.raises(VulnAgentError, match="analysis"):
            parse_repair_response(json.dumps({"edits": []}))

    def test_rejects_an_edit_that_is_missing_its_search_text(self):
        with pytest.raises(VulnAgentError, match="search"):
            parse_repair_response(
                json.dumps({"analysis": "x", "edits": [{"path": "a.ts", "replace": "b"}]})
            )

    def test_rejects_a_confidence_outside_zero_to_one(self):
        with pytest.raises(VulnAgentError, match="confidence"):
            parse_repair_response(json.dumps({"analysis": "x", "edits": [], "confidence": 7}))

    def test_rejects_an_empty_response(self):
        with pytest.raises(VulnAgentError):
            parse_repair_response("")

    def test_the_error_message_can_be_shown_to_the_model_on_a_retry(self):
        with pytest.raises(VulnAgentError) as caught:
            parse_repair_response(json.dumps({"edits": []}))

        assert "analysis" in str(caught.value)


class TestApplyingEdits:
    def test_applies_an_edit_that_matches_once(self):
        response = RepairResponse.model_validate(VALID)

        updated = response.apply_to({"src/auth.ts": "const t = jwt.sign(p)\n"})

        assert updated == {"src/auth.ts": "const t = await jwt.sign(p)\n"}

    def test_refuses_an_edit_whose_search_text_is_not_there(self):
        response = RepairResponse.model_validate(VALID)

        with pytest.raises(VulnAgentError, match="not found"):
            response.apply_to({"src/auth.ts": "const t = sign(p)\n"})

    def test_refuses_an_edit_whose_search_text_appears_more_than_once(self):
        response = RepairResponse.model_validate(VALID)

        with pytest.raises(VulnAgentError, match="more than once"):
            response.apply_to({"src/auth.ts": "jwt.sign(p)\njwt.sign(p)\n"})

    def test_refuses_an_edit_to_a_file_that_was_never_fetched(self):
        response = RepairResponse.model_validate(VALID)

        with pytest.raises(VulnAgentError, match=r"src/auth\.ts"):
            response.apply_to({"src/other.ts": "x"})

    def test_leaves_untouched_files_out_of_the_result(self):
        response = RepairResponse.model_validate(VALID)

        updated = response.apply_to(
            {"src/auth.ts": "const t = jwt.sign(p)\n", "src/other.ts": "x\n"}
        )

        assert list(updated) == ["src/auth.ts"]


class TestTheRepairPrompt:
    def test_the_system_prompt_forbids_the_things_safety_rules_enforce(self):
        text = REPAIR_SYSTEM_PROMPT.lower()

        assert "downgrade" in text
        assert "lockfile" in text
        assert "json" in text

    @pytest.fixture
    def prompt(self):
        return build_repair_prompt(
            upgrade_plan="lodash 4.17.20 -> 4.17.21",
            log_excerpt="TypeError: jwt.sign is not a function",
            similar_fixes=["Past fix: await the call"],
            files={"src/auth.ts": "const t = jwt.sign(p)"},
            ecosystem_hints=["Check the changelog"],
            attempt=2,
            max_attempts=3,
            previous_attempts=["Attempt 1: added await, still failed"],
        )

    @pytest.mark.parametrize(
        "section",
        [
            "UPGRADE_PLAN",
            "CI_LOG_EXCERPT",
            "SIMILAR_PAST_FIXES",
            "FILES",
            "ECOSYSTEM_HINTS",
            "ATTEMPT",
            "PREVIOUS_ATTEMPTS",
        ],
    )
    def test_includes_every_section_the_contract_names(self, prompt, section):
        assert section in prompt

    def test_tells_the_model_which_attempt_this_is(self, prompt):
        assert "2 of 3" in prompt

    def test_labels_each_file_with_its_path(self, prompt):
        assert "src/auth.ts" in prompt

    def test_says_so_explicitly_when_there_are_no_past_fixes(self):
        prompt = build_repair_prompt(
            upgrade_plan="x",
            log_excerpt="y",
            similar_fixes=[],
            files={},
            ecosystem_hints=[],
            attempt=1,
            max_attempts=3,
            previous_attempts=[],
        )

        assert "SIMILAR_PAST_FIXES" in prompt
        assert "none" in prompt.lower()

    def test_redacts_a_secret_that_was_sitting_in_a_source_file(self):
        prompt = build_repair_prompt(
            upgrade_plan="x",
            log_excerpt="y",
            similar_fixes=[],
            files={"src/config.ts": 'const key = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"'},
            ecosystem_hints=[],
            attempt=1,
            max_attempts=3,
            previous_attempts=[],
        )

        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in prompt
