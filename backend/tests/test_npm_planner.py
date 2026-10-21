import pytest

from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.models import (
    BumpDirect,
    BumpParent,
    DepEdge,
    DepGraph,
    DepNode,
    Override,
    VulnFinding,
)


class FakeRegistry:
    """A registry with a fixed catalogue, so planning is deterministic."""

    def __init__(
        self,
        versions: dict[str, list[str]] | None = None,
        dependencies: dict[tuple[str, str], dict[str, str]] | None = None,
    ) -> None:
        self.versions = versions or {}
        self.dependencies = dependencies or {}
        self.calls: list[str] = []

    def list_versions(self, name: str) -> list[str]:
        self.calls.append(f"list_versions({name})")
        return self.versions.get(name, [])

    def get_dependencies(self, name: str, version: str) -> dict[str, str]:
        self.calls.append(f"get_dependencies({name},{version})")
        return self.dependencies.get((name, version), {})


def purl_of(name: str, version: str) -> str:
    return f"pkg:npm/{name.replace('@', '%40', 1)}@{version}"


def graph_of(
    direct: dict[str, tuple[str, str]], transitive: dict[str, tuple[str, str, str]] | None = None
) -> DepGraph:
    """direct: name -> (version, declared range). transitive: name -> (version, parent, range)."""
    nodes: dict[str, DepNode] = {}
    edges: list[DepEdge] = []

    for name, (version, declared) in direct.items():
        purl = purl_of(name, version)
        nodes[purl] = DepNode(purl=purl, name=name, version=version, is_direct=True, is_dev=False)
        edges.append(DepEdge(parent="ROOT", child=purl, requested_range=declared))

    for name, (version, parent, declared) in (transitive or {}).items():
        purl = purl_of(name, version)
        nodes[purl] = DepNode(purl=purl, name=name, version=version, is_direct=False, is_dev=False)
        edges.append(DepEdge(parent=parent, child=purl, requested_range=declared))

    return DepGraph(ecosystem="npm", nodes=nodes, edges=edges)


def finding(name: str, version: str, fixed: list[str], osv_id: str = "GHSA-test") -> VulnFinding:
    return VulnFinding(
        osv_id=osv_id,
        aliases=[],
        purl=purl_of(name, version),
        fixed_versions=fixed,
        severity="high",
    )


@pytest.fixture
def adapter():
    return NpmAdapter()


def plan_for(adapter, findings, graph, *, registry=None, allow_major_bumps=False):
    return adapter.plan_upgrades(
        findings,
        graph,
        allow_major_bumps=allow_major_bumps,
        registry=registry or FakeRegistry(),
    )


class TestDirectDependencies:
    def test_bumps_a_direct_dependency_to_the_fixed_version(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", ["4.17.21"])],
            graph_of({"lodash": ("4.17.20", "^4.17.20")}),
        )

        assert plan.actions == [
            BumpDirect(
                name="lodash",
                from_version="4.17.20",
                to_version="4.17.21",
                manifest_path="package.json",
            )
        ]

    def test_records_the_advisory_the_bump_resolves(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", ["4.17.21"], osv_id="GHSA-29mw")],
            graph_of({"lodash": ("4.17.20", "^4.17.20")}),
        )

        assert plan.resolves == ["GHSA-29mw"]
        assert plan.unresolved == []

    def test_chooses_the_lowest_fix_above_the_installed_version(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", ["3.9.0", "4.17.21", "4.18.0"])],
            graph_of({"lodash": ("4.17.20", "^4.17.20")}),
        )

        assert plan.actions[0].to_version == "4.17.21"

    def test_leaves_a_package_alone_when_every_fix_is_already_installed(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.21", ["4.17.21"])],
            graph_of({"lodash": ("4.17.21", "^4.17.21")}),
        )

        assert plan.actions == []
        assert [item.reason for item in plan.unresolved] == ["no_fix"]

    def test_reports_an_advisory_with_no_published_fix_as_unfixable(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", [], osv_id="GHSA-nofix")],
            graph_of({"lodash": ("4.17.20", "^4.17.20")}),
        )

        assert plan.actions == []
        assert plan.unresolved[0].osv_id == "GHSA-nofix"
        assert plan.unresolved[0].reason == "no_fix"


class TestRangeStyle:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("^4.17.20", "^4.17.21"),
            ("~4.17.20", "~4.17.21"),
            ("4.17.20", "4.17.21"),
            ("=4.17.20", "4.17.21"),
        ],
    )
    def test_keeps_the_range_operator_the_manifest_already_used(self, adapter, declared, expected):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", ["4.17.21"])],
            graph_of({"lodash": ("4.17.20", declared)}),
        )

        assert adapter.manifest_range_for(plan.actions[0], declared) == expected

    def test_falls_back_to_a_caret_range_for_a_range_it_cannot_mirror(self, adapter):
        plan = plan_for(
            adapter,
            [finding("lodash", "4.17.20", ["4.17.21"])],
            graph_of({"lodash": ("4.17.20", ">=4.0.0 <5.0.0")}),
        )

        assert adapter.manifest_range_for(plan.actions[0], ">=4.0.0 <5.0.0") == "^4.17.21"


class TestMajorBumps:
    def test_refuses_a_major_bump_unless_the_repo_allows_it(self, adapter):
        plan = plan_for(
            adapter,
            [finding("jsonwebtoken", "8.5.1", ["9.0.0"], osv_id="GHSA-jwt")],
            graph_of({"jsonwebtoken": ("8.5.1", "^8.5.1")}),
        )

        assert plan.actions == []
        assert plan.unresolved[0].reason == "needs_major"

    def test_takes_the_major_bump_when_the_repo_allows_it(self, adapter):
        plan = plan_for(
            adapter,
            [finding("jsonwebtoken", "8.5.1", ["9.0.0"])],
            graph_of({"jsonwebtoken": ("8.5.1", "^8.5.1")}),
            allow_major_bumps=True,
        )

        assert plan.actions[0].to_version == "9.0.0"

    def test_flags_the_major_bump_so_the_pull_request_can_warn_about_it(self, adapter):
        plan = plan_for(
            adapter,
            [finding("jsonwebtoken", "8.5.1", ["9.0.0"])],
            graph_of({"jsonwebtoken": ("8.5.1", "^8.5.1")}),
            allow_major_bumps=True,
        )

        assert plan.major_bumps == ["jsonwebtoken"]

    def test_prefers_a_minor_fix_over_a_major_one_when_both_are_published(self, adapter):
        plan = plan_for(
            adapter,
            [finding("jsonwebtoken", "8.5.1", ["8.5.2", "9.0.0"])],
            graph_of({"jsonwebtoken": ("8.5.1", "^8.5.1")}),
        )

        assert plan.actions[0].to_version == "8.5.2"
        assert plan.major_bumps == []

    def test_a_zero_major_minor_bump_counts_as_breaking(self, adapter):
        plan = plan_for(
            adapter,
            [finding("tiny", "0.1.0", ["0.2.0"])],
            graph_of({"tiny": ("0.1.0", "^0.1.0")}),
        )

        assert plan.actions == []
        assert plan.unresolved[0].reason == "needs_major"


class TestTransitiveDependencies:
    @pytest.fixture
    def graph(self):
        return graph_of(
            {"express": ("4.16.0", "^4.16.0")},
            {"qs": ("6.5.2", purl_of("express", "4.16.0"), "6.5.2")},
        )

    @pytest.fixture
    def registry(self):
        return FakeRegistry(
            versions={"express": ["4.16.0", "4.16.1", "4.17.0", "4.17.1", "5.0.0"]},
            dependencies={
                ("express", "4.16.1"): {"qs": "6.5.1"},
                ("express", "4.17.0"): {"qs": "6.5.2"},
                ("express", "4.17.1"): {"qs": "6.7.0"},
                ("express", "5.0.0"): {"qs": "6.11.0"},
            },
        )

    def test_bumps_the_parent_that_pulls_in_the_vulnerable_package(self, adapter, graph, registry):
        plan = plan_for(adapter, [finding("qs", "6.5.2", ["6.5.3"])], graph, registry=registry)

        assert plan.actions == [
            BumpParent(
                parent_name="express",
                from_version="4.16.0",
                to_version="4.17.1",
                reason=purl_of("qs", "6.5.2"),
                manifest_path="package.json",
            )
        ]

    def test_picks_the_lowest_parent_version_that_pulls_in_a_fixed_copy(
        self, adapter, graph, registry
    ):
        plan = plan_for(adapter, [finding("qs", "6.5.2", ["6.5.3"])], graph, registry=registry)

        assert plan.actions[0].to_version == "4.17.1"

    def test_will_not_cross_a_major_on_the_parent_either(self, adapter, graph):
        registry = FakeRegistry(
            versions={"express": ["4.16.0", "5.0.0"]},
            dependencies={("express", "5.0.0"): {"qs": "6.11.0"}},
        )

        plan = plan_for(adapter, [finding("qs", "6.5.2", ["6.5.3"])], graph, registry=registry)

        assert [type(action) for action in plan.actions] == [Override]

    def test_overrides_the_package_when_no_parent_version_fixes_it(self, adapter, graph):
        registry = FakeRegistry(
            versions={"express": ["4.16.0", "4.16.1"]},
            dependencies={("express", "4.16.1"): {"qs": "6.5.1"}},
        )

        plan = plan_for(adapter, [finding("qs", "6.5.2", ["6.5.3"])], graph, registry=registry)

        assert plan.actions == [
            Override(
                name="qs",
                to_version="6.5.3",
                reason=purl_of("qs", "6.5.2"),
                manifest_path="package.json",
            )
        ]

    def test_overrides_when_the_parent_publishes_no_newer_version_at_all(self, adapter, graph):
        plan = plan_for(
            adapter,
            [finding("qs", "6.5.2", ["6.5.3"])],
            graph,
            registry=FakeRegistry(versions={"express": ["4.16.0"]}),
        )

        assert [type(action) for action in plan.actions] == [Override]

    def test_records_which_vulnerable_package_the_parent_bump_is_for(
        self, adapter, graph, registry
    ):
        plan = plan_for(adapter, [finding("qs", "6.5.2", ["6.5.3"])], graph, registry=registry)

        assert plan.actions[0].reason == purl_of("qs", "6.5.2")


class TestConflicts:
    def test_reports_a_conflict_when_an_override_would_contradict_the_manifest(self, adapter):
        graph = graph_of(
            {"qs": ("6.5.2", "~6.5.2"), "express": ("4.16.0", "^4.16.0")},
            {"inner": ("1.0.0", purl_of("express", "4.16.0"), "1.0.0")},
        )
        graph.nodes[purl_of("qs", "6.5.2")].is_direct = False
        graph.edges.append(
            DepEdge(
                parent=purl_of("express", "4.16.0"),
                child=purl_of("qs", "6.5.2"),
                requested_range="6.5.2",
            )
        )

        plan = plan_for(
            adapter,
            [finding("qs", "6.5.2", ["7.0.0"], osv_id="GHSA-conflict")],
            graph,
            registry=FakeRegistry(versions={"express": ["4.16.0"]}),
        )

        assert plan.actions == []
        assert plan.unresolved[0].reason == "conflict"


class TestMergingActions:
    def test_merges_two_advisories_on_one_package_into_a_single_bump(self, adapter):
        plan = plan_for(
            adapter,
            [
                finding("lodash", "4.17.15", ["4.17.19"], osv_id="GHSA-a"),
                finding("lodash", "4.17.15", ["4.17.21"], osv_id="GHSA-b"),
            ],
            graph_of({"lodash": ("4.17.15", "^4.17.15")}),
        )

        assert len(plan.actions) == 1
        assert plan.actions[0].to_version == "4.17.21"

    def test_both_advisories_count_as_resolved_by_the_merged_bump(self, adapter):
        plan = plan_for(
            adapter,
            [
                finding("lodash", "4.17.15", ["4.17.19"], osv_id="GHSA-a"),
                finding("lodash", "4.17.15", ["4.17.21"], osv_id="GHSA-b"),
            ],
            graph_of({"lodash": ("4.17.15", "^4.17.15")}),
        )

        assert sorted(plan.resolves) == ["GHSA-a", "GHSA-b"]

    def test_keeps_separate_packages_as_separate_actions(self, adapter):
        plan = plan_for(
            adapter,
            [
                finding("lodash", "4.17.20", ["4.17.21"], osv_id="GHSA-a"),
                finding("minimist", "1.2.5", ["1.2.6"], osv_id="GHSA-b"),
            ],
            graph_of({"lodash": ("4.17.20", "^4.17.20"), "minimist": ("1.2.5", "^1.2.5")}),
        )

        assert {action.name for action in plan.actions} == {"lodash", "minimist"}


class TestEmptyPlans:
    def test_a_scan_with_no_findings_produces_nothing_to_do(self, adapter):
        plan = plan_for(adapter, [], graph_of({"lodash": ("4.17.21", "^4.17.21")}))

        assert plan.is_empty()
        assert plan.ecosystem == "npm"

    def test_a_finding_for_a_package_that_is_not_installed_is_skipped(self, adapter):
        plan = plan_for(
            adapter,
            [finding("ghost", "1.0.0", ["1.0.1"])],
            graph_of({"lodash": ("4.17.21", "^4.17.21")}),
        )

        assert plan.is_empty()
