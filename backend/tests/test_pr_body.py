from vulnagent.core.models import BumpDirect, BumpParent, Override, Unresolved, UpgradePlan
from vulnagent.github.pr_body import (
    LOG_END,
    LOG_START,
    commit_message,
    pr_title,
    render_pr_body,
    update_agent_log,
)

LODASH = "pkg:npm/lodash@4.17.20"
QS = "pkg:npm/qs@6.5.2"
MINIMIST = "pkg:npm/minimist@0.0.8"

PLAN = UpgradePlan(
    ecosystem="npm",
    actions=[
        BumpDirect(
            name="lodash",
            from_version="4.17.20",
            to_version="4.17.21",
            manifest_path="package.json",
        ),
        BumpParent(
            parent_name="express",
            from_version="4.16.0",
            to_version="4.17.1",
            reason=QS,
            manifest_path="package.json",
        ),
        Override(
            name="minimist", to_version="1.2.6", reason=MINIMIST, manifest_path="package.json"
        ),
    ],
    resolves=["GHSA-lodash", "GHSA-qs", "GHSA-minimist"],
)

SEVERITIES = {LODASH: "high", QS: "medium", MINIMIST: "critical"}
ADVISORIES = {LODASH: "GHSA-lodash", QS: "GHSA-qs", MINIMIST: "GHSA-minimist"}


def body_for(plan=PLAN, **overrides) -> str:
    return render_pr_body(
        plan,
        **{
            "severities": SEVERITIES,
            "advisory_for": ADVISORIES,
            "max_attempts": 3,
            **overrides,
        },
    )


class TestTitleAndCommitMessage:
    def test_the_title_counts_what_is_fixed(self):
        assert pr_title(3) == "fix(deps): resolve 3 vulnerabilities"

    def test_one_vulnerability_reads_as_singular(self):
        assert pr_title(1) == "fix(deps): resolve 1 vulnerability"

    def test_the_commit_message_is_tagged_so_the_agent_can_recognise_it(self):
        assert commit_message(3) == "fix(deps): resolve 3 vulnerabilities [vulnagent]"


class TestTheBody:
    def test_leads_with_how_many_vulnerabilities_are_resolved(self):
        assert "Resolves **3**" in body_for()

    def test_breaks_the_count_down_by_severity_worst_first(self):
        assert "(1 critical, 1 high, 1 medium)" in body_for()

    def test_lists_a_direct_bump_with_its_versions(self):
        assert "| `lodash` | `4.17.20` → `4.17.21` | high | direct |" in body_for()

    def test_explains_which_parent_a_transitive_fix_goes_through(self):
        assert "`qs` (via `express`)" in body_for()

    def test_labels_a_parent_bump_as_transitive(self):
        assert "transitive (parent bump)" in body_for()

    def test_shows_an_override_as_a_pin(self):
        assert "pinned to `1.2.6`" in body_for()
        assert "transitive (override)" in body_for()

    def test_names_the_config_file_and_the_retry_budget(self):
        body = body_for(max_attempts=5)

        assert "`.vulnagent.yml`" in body
        assert "Max CI repair attempts: 5" in body


class TestWhatCouldNotBeFixed:
    def test_explains_an_advisory_with_no_published_fix(self):
        plan = PLAN.model_copy(update={"unresolved": [Unresolved(osv_id="CVE-1", reason="no_fix")]})

        assert "CVE-1: no fixed version available" in body_for(plan)

    def test_explains_a_fix_held_back_by_the_major_bump_setting(self):
        plan = PLAN.model_copy(
            update={"unresolved": [Unresolved(osv_id="CVE-2", reason="needs_major")]}
        )

        assert "allow_major_bumps" in body_for(plan)

    def test_leaves_the_section_out_when_everything_was_fixed(self):
        assert "Not fixed" not in body_for()

    def test_warns_about_major_bumps_that_were_taken(self):
        plan = PLAN.model_copy(update={"major_bumps": ["jsonwebtoken"]})

        body = body_for(plan)

        assert "Major version bumps" in body
        assert "`jsonwebtoken`" in body


class TestTheAgentLog:
    def test_starts_with_a_placeholder(self):
        assert "_Updated automatically as CI runs._" in body_for()

    def test_is_delimited_so_it_can_be_rewritten_later(self):
        body = body_for()

        assert body.index(LOG_START) < body.index(LOG_END)

    def test_rewrites_only_the_log_section(self):
        updated = update_agent_log(body_for(), ["CI failed: TypeError", "Pushed a patch"])

        assert "CI failed: TypeError" in updated
        assert "Resolves **3**" in updated

    def test_drops_the_previous_log_rather_than_appending_to_it(self):
        once = update_agent_log(body_for(), ["first"])
        twice = update_agent_log(once, ["second"])

        assert "first" not in twice
        assert "second" in twice

    def test_keeps_anything_a_human_added_below_the_log(self):
        body = body_for() + "\n\nPlease also check the changelog. - a reviewer"

        updated = update_agent_log(body, ["attempt 1"])

        assert "Please also check the changelog." in updated

    def test_appends_a_log_section_to_a_body_that_has_none(self):
        updated = update_agent_log("A body written by someone else.", ["attempt 1"])

        assert "attempt 1" in updated
        assert "A body written by someone else." in updated


class TestEmptyPlan:
    def test_renders_without_a_table_body_when_nothing_was_planned(self):
        body = body_for(UpgradePlan(ecosystem="npm"))

        assert "Resolves **0**" in body
        assert "| Advisory | Package |" in body
