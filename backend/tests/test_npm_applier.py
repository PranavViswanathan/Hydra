import json

import pytest

from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.models import BumpDirect, BumpParent, Override, UpgradePlan

MANIFEST = """{
  "name": "test-app",
  "version": "1.0.0",
  "scripts": {
    "test": "vitest run"
  },
  "dependencies": {
    "express": "^4.16.0",
    "lodash": "^4.17.20"
  },
  "devDependencies": {
    "vitest": "~1.6.0"
  }
}
"""

LOCKFILE = '{"name": "test-app", "lockfileVersion": 3, "packages": {}}\n'


class FakeRegenerator:
    """Stands in for the Node helper function that runs npm (§6.4)."""

    def __init__(self, lockfile: str | None = None) -> None:
        self.lockfile = lockfile if lockfile is not None else '{"regenerated": true}\n'
        self.received: dict[str, str] | None = None

    def regenerate(self, files: dict[str, str]) -> dict[str, str]:
        self.received = dict(files)
        return {"package-lock.json": self.lockfile}


@pytest.fixture
def adapter():
    return NpmAdapter()


@pytest.fixture
def files():
    return {"package.json": MANIFEST, "package-lock.json": LOCKFILE}


def plan_with(*actions) -> UpgradePlan:
    return UpgradePlan(ecosystem="npm", actions=list(actions))


def manifest_from(patches) -> dict:
    return json.loads(next(p.new_contents for p in patches if p.path == "package.json"))


def bump_lodash(to="4.17.21") -> BumpDirect:
    return BumpDirect(
        name="lodash", from_version="4.17.20", to_version=to, manifest_path="package.json"
    )


class TestDirectBumps:
    def test_rewrites_the_dependency_to_the_new_version(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        assert manifest_from(patches)["dependencies"]["lodash"] == "^4.17.21"

    def test_keeps_the_range_operator_the_manifest_already_used(self, adapter, files):
        action = BumpDirect(
            name="vitest", from_version="1.6.0", to_version="1.6.1", manifest_path="package.json"
        )

        patches = adapter.apply_upgrades(plan_with(action), files, FakeRegenerator())

        assert manifest_from(patches)["devDependencies"]["vitest"] == "~1.6.1"

    def test_leaves_the_other_dependencies_untouched(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        assert manifest_from(patches)["dependencies"]["express"] == "^4.16.0"

    def test_does_not_add_a_package_the_manifest_never_declared(self, adapter, files):
        """A transitive package reached by bumping something else is not a new direct dep."""
        action = BumpDirect(
            name="ghost", from_version="1.0.0", to_version="1.0.1", manifest_path="package.json"
        )

        patches = adapter.apply_upgrades(plan_with(action, bump_lodash()), files, FakeRegenerator())

        assert "ghost" not in manifest_from(patches)["dependencies"]


class TestParentBumps:
    def test_rewrites_the_parent_dependency(self, adapter, files):
        action = BumpParent(
            parent_name="express",
            from_version="4.16.0",
            to_version="4.17.1",
            reason="pkg:npm/qs@6.5.2",
            manifest_path="package.json",
        )

        patches = adapter.apply_upgrades(plan_with(action), files, FakeRegenerator())

        assert manifest_from(patches)["dependencies"]["express"] == "^4.17.1"


class TestOverrides:
    def test_adds_an_overrides_section_when_the_manifest_has_none(self, adapter, files):
        action = Override(
            name="qs", to_version="6.5.3", reason="pkg:npm/qs@6.5.2", manifest_path="package.json"
        )

        patches = adapter.apply_upgrades(plan_with(action), files, FakeRegenerator())

        assert manifest_from(patches)["overrides"] == {"qs": "6.5.3"}

    def test_pins_the_exact_version_rather_than_a_range(self, adapter, files):
        action = Override(
            name="qs", to_version="6.5.3", reason="pkg:npm/qs@6.5.2", manifest_path="package.json"
        )

        patches = adapter.apply_upgrades(plan_with(action), files, FakeRegenerator())

        assert manifest_from(patches)["overrides"]["qs"] == "6.5.3"

    def test_merges_into_an_existing_overrides_section(self, adapter):
        files = {
            "package.json": json.dumps(
                {"name": "a", "dependencies": {}, "overrides": {"minimist": "1.2.6"}}, indent=2
            )
            + "\n",
            "package-lock.json": LOCKFILE,
        }
        action = Override(
            name="qs", to_version="6.5.3", reason="pkg:npm/qs@6.5.2", manifest_path="package.json"
        )

        patches = adapter.apply_upgrades(plan_with(action), files, FakeRegenerator())

        assert manifest_from(patches)["overrides"] == {"minimist": "1.2.6", "qs": "6.5.3"}


class TestFormattingIsPreserved:
    def test_keeps_the_original_key_order(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert list(json.loads(text)) == [
            "name",
            "version",
            "scripts",
            "dependencies",
            "devDependencies",
        ]

    def test_keeps_two_space_indentation(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert '\n  "name": "test-app"' in text

    def test_keeps_four_space_indentation_when_that_is_what_the_repo_uses(self, adapter):
        files = {
            "package.json": json.dumps(
                {"name": "a", "dependencies": {"lodash": "^4.17.20"}}, indent=4
            )
            + "\n",
            "package-lock.json": LOCKFILE,
        }

        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())
        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert '\n    "name": "a"' in text

    def test_keeps_tab_indentation(self, adapter):
        files = {
            "package.json": (
                '{\n\t"name": "a",\n\t"dependencies": {\n\t\t"lodash": "^4.17.20"\n\t}\n}\n'
            ),
            "package-lock.json": LOCKFILE,
        }

        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())
        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert '\n\t"name": "a"' in text

    def test_keeps_the_trailing_newline(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert text.endswith("}\n")

    def test_does_not_add_a_trailing_newline_the_repo_did_not_have(self, adapter):
        files = {
            "package.json": '{"name": "a", "dependencies": {"lodash": "^4.17.20"}}',
            "package-lock.json": LOCKFILE,
        }

        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())
        text = next(p.new_contents for p in patches if p.path == "package.json")

        assert not text.endswith("\n")


class TestLockfileRegeneration:
    def test_hands_the_updated_manifest_to_the_regenerator(self, adapter, files):
        regenerator = FakeRegenerator()

        adapter.apply_upgrades(plan_with(bump_lodash()), files, regenerator)

        assert regenerator.received is not None
        assert (
            json.loads(regenerator.received["package.json"])["dependencies"]["lodash"] == "^4.17.21"
        )

    def test_also_hands_over_the_current_lockfile(self, adapter, files):
        regenerator = FakeRegenerator()

        adapter.apply_upgrades(plan_with(bump_lodash()), files, regenerator)

        assert regenerator.received is not None
        assert regenerator.received["package-lock.json"] == LOCKFILE

    def test_returns_a_patch_for_both_files(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator())

        assert {patch.path for patch in patches} == {"package.json", "package-lock.json"}

    def test_returns_the_regenerated_lockfile(self, adapter, files):
        patches = adapter.apply_upgrades(
            plan_with(bump_lodash()), files, FakeRegenerator('{"new": true}\n')
        )

        assert (
            next(p.new_contents for p in patches if p.path == "package-lock.json")
            == '{"new": true}\n'
        )

    def test_omits_the_lockfile_patch_when_regeneration_changed_nothing(self, adapter, files):
        patches = adapter.apply_upgrades(plan_with(bump_lodash()), files, FakeRegenerator(LOCKFILE))

        assert {patch.path for patch in patches} == {"package.json"}


class TestNothingToDo:
    def test_an_empty_plan_produces_no_patches_and_runs_no_npm(self, adapter, files):
        regenerator = FakeRegenerator()

        patches = adapter.apply_upgrades(plan_with(), files, regenerator)

        assert patches == []
        assert regenerator.received is None

    def test_a_plan_that_changes_nothing_in_the_manifest_runs_no_npm(self, adapter, files):
        action = BumpDirect(
            name="ghost", from_version="1.0.0", to_version="1.0.1", manifest_path="package.json"
        )
        regenerator = FakeRegenerator()

        patches = adapter.apply_upgrades(plan_with(action), files, regenerator)

        assert patches == []
        assert regenerator.received is None
