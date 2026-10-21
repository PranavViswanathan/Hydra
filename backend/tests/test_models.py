import pytest
from pydantic import ValidationError

from vulnagent.core.models import (
    BumpDirect,
    BumpParent,
    DepEdge,
    DepGraph,
    DepNode,
    Override,
    UpgradePlan,
    meets_threshold,
    severity_rank,
)


def a_plan(**overrides: object) -> dict:
    return {
        "ecosystem": "npm",
        "actions": [],
        "resolves": [],
        "unresolved": [],
        "major_bumps": [],
        **overrides,
    }


def test_plan_actions_deserialize_into_the_class_named_by_their_kind():
    plan = UpgradePlan.model_validate(
        a_plan(
            actions=[
                {
                    "kind": "bump_direct",
                    "name": "lodash",
                    "from_version": "4.17.20",
                    "to_version": "4.17.21",
                    "manifest_path": "package.json",
                },
                {
                    "kind": "bump_parent",
                    "parent_name": "express",
                    "from_version": "4.16.0",
                    "to_version": "4.17.1",
                    "reason": "pkg:npm/qs@6.5.2",
                    "manifest_path": "package.json",
                },
                {
                    "kind": "override",
                    "name": "minimist",
                    "to_version": "1.2.6",
                    "reason": "pkg:npm/minimist@0.0.8",
                    "manifest_path": "package.json",
                },
            ]
        )
    )

    assert [type(action) for action in plan.actions] == [BumpDirect, BumpParent, Override]


def test_plan_survives_a_json_round_trip_with_its_action_types_intact():
    original = UpgradePlan.model_validate(
        a_plan(
            actions=[
                {
                    "kind": "override",
                    "name": "minimist",
                    "to_version": "1.2.6",
                    "reason": "pkg:npm/minimist@0.0.8",
                    "manifest_path": "package.json",
                }
            ],
            resolves=["GHSA-vh95-rmgr-6w4m"],
        )
    )

    restored = UpgradePlan.model_validate_json(original.model_dump_json())

    assert restored == original
    assert isinstance(restored.actions[0], Override)


def test_plan_rejects_an_action_with_an_unknown_kind():
    with pytest.raises(ValidationError):
        UpgradePlan.model_validate(a_plan(actions=[{"kind": "uninstall", "name": "lodash"}]))


def test_an_empty_plan_is_valid_and_resolves_nothing():
    plan = UpgradePlan.model_validate(a_plan())

    assert plan.actions == []
    assert plan.resolves == []


def test_dependency_graph_keeps_root_edges_distinct_from_package_edges():
    graph = DepGraph(
        ecosystem="npm",
        nodes={
            "pkg:npm/express@4.16.0": DepNode(
                purl="pkg:npm/express@4.16.0",
                name="express",
                version="4.16.0",
                is_direct=True,
                is_dev=False,
            )
        },
        edges=[
            DepEdge(parent="ROOT", child="pkg:npm/express@4.16.0", requested_range="^4.16.0"),
            DepEdge(
                parent="pkg:npm/express@4.16.0",
                child="pkg:npm/qs@6.5.2",
                requested_range="6.5.2",
            ),
        ],
    )

    assert graph.edges[0].parent == "ROOT"
    assert graph.edges[1].parent == "pkg:npm/express@4.16.0"


def test_severity_sorts_from_unknown_up_to_critical():
    ordered = sorted(["high", "low", "critical", "medium"], key=severity_rank)

    assert ordered == ["low", "medium", "high", "critical"]


@pytest.mark.parametrize(
    ("severity", "threshold", "expected"),
    [
        ("critical", "high", True),
        ("high", "high", True),
        ("medium", "high", False),
        ("low", "low", True),
        ("unknown", "low", True),
        ("unknown", "medium", False),
    ],
)
def test_threshold_admits_only_severities_at_or_above_it(severity, threshold, expected):
    assert meets_threshold(severity, threshold) is expected
