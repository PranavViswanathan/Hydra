import pytest

from tests.helpers import npm_files
from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.errors import UnsupportedLockfileError


@pytest.fixture
def adapter():
    return NpmAdapter()


def names_of(graph) -> set[str]:
    return {node.name for node in graph.nodes.values()}


def edges_from(graph, parent: str) -> dict[str, str]:
    """Child purl -> requested range, for every edge leaving `parent`."""
    return {edge.child: edge.requested_range for edge in graph.edges if edge.parent == parent}


class TestDetect:
    def test_detects_a_repository_with_both_npm_files_at_the_root(self, adapter):
        assert adapter.detect(["package.json", "package-lock.json", "src/index.ts"]) is True

    def test_ignores_a_repository_with_a_manifest_but_no_lockfile(self, adapter):
        assert adapter.detect(["package.json", "src/index.ts"]) is False

    def test_ignores_a_repository_with_no_npm_files_at_all(self, adapter):
        assert adapter.detect(["pom.xml", "src/Main.java"]) is False

    def test_ignores_npm_files_that_only_exist_in_a_subdirectory(self, adapter):
        assert (
            adapter.detect(["packages/api/package.json", "packages/api/package-lock.json"]) is False
        )


class TestParseSimpleTree:
    @pytest.fixture
    def graph(self, adapter):
        return adapter.parse_dependencies(npm_files("v3-simple"))

    def test_records_every_installed_package_as_a_node(self, graph):
        assert names_of(graph) == {"accepts", "express", "lodash", "qs", "vitest"}

    def test_does_not_create_a_node_for_the_root_project_itself(self, graph):
        assert "test-app" not in names_of(graph)

    def test_names_the_ecosystem_it_parsed(self, graph):
        assert graph.ecosystem == "npm"

    def test_keys_nodes_by_purl(self, graph):
        assert graph.nodes["pkg:npm/lodash@4.17.20"].version == "4.17.20"

    def test_marks_packages_listed_in_the_manifest_as_direct(self, graph):
        direct = {node.name for node in graph.nodes.values() if node.is_direct}

        assert direct == {"express", "lodash", "vitest"}

    def test_marks_packages_only_reached_through_others_as_transitive(self, graph):
        assert graph.nodes["pkg:npm/qs@6.5.2"].is_direct is False

    def test_carries_the_dev_flag_through_from_the_lockfile(self, graph):
        assert graph.nodes["pkg:npm/vitest@1.6.0"].is_dev is True
        assert graph.nodes["pkg:npm/express@4.16.0"].is_dev is False

    def test_connects_direct_dependencies_to_the_root(self, graph):
        assert edges_from(graph, "ROOT") == {
            "pkg:npm/express@4.16.0": "^4.16.0",
            "pkg:npm/lodash@4.17.20": "^4.17.20",
            "pkg:npm/vitest@1.6.0": "^1.6.0",
        }

    def test_connects_a_package_to_the_dependencies_it_requested(self, graph):
        assert edges_from(graph, "pkg:npm/express@4.16.0") == {
            "pkg:npm/accepts@1.3.8": "~1.3.5",
            "pkg:npm/qs@6.5.2": "6.5.2",
        }

    def test_a_transitive_package_traces_back_to_the_root(self, adapter, graph):
        paths = adapter.paths_to_root(graph, "pkg:npm/qs@6.5.2")

        assert paths == [["ROOT", "pkg:npm/express@4.16.0", "pkg:npm/qs@6.5.2"]]


class TestParseNestedTree:
    @pytest.fixture
    def graph(self, adapter):
        return adapter.parse_dependencies(npm_files("v3-nested"))

    def test_keeps_both_installed_copies_of_a_package(self, graph):
        assert "pkg:npm/qs@6.11.2" in graph.nodes
        assert "pkg:npm/qs@6.5.2" in graph.nodes

    def test_a_nested_dependency_resolves_to_the_copy_beside_its_parent(self, graph):
        assert edges_from(graph, "pkg:npm/express@4.16.0")["pkg:npm/qs@6.5.2"] == "6.5.2"

    def test_the_root_resolves_to_the_hoisted_copy_instead(self, graph):
        assert "pkg:npm/qs@6.11.2" in edges_from(graph, "ROOT")

    def test_a_package_without_a_nested_copy_falls_back_to_the_hoisted_one(self, graph):
        assert "pkg:npm/side-channel@1.0.6" in edges_from(graph, "pkg:npm/qs@6.11.2")

    def test_resolution_walks_up_through_intermediate_node_modules_directories(self, graph):
        assert "pkg:npm/mime@1.4.1" in edges_from(graph, "pkg:npm/send@0.16.0")

    def test_only_the_hoisted_copy_of_a_package_counts_as_direct(self, graph):
        assert graph.nodes["pkg:npm/qs@6.11.2"].is_direct is True
        assert graph.nodes["pkg:npm/qs@6.5.2"].is_direct is False

    def test_a_nested_package_traces_back_to_the_root_through_its_parent(self, adapter, graph):
        paths = adapter.paths_to_root(graph, "pkg:npm/mime@1.4.1")

        assert paths == [
            ["ROOT", "pkg:npm/express@4.16.0", "pkg:npm/send@0.16.0", "pkg:npm/mime@1.4.1"]
        ]


class TestParseScopedPackages:
    @pytest.fixture
    def graph(self, adapter):
        return adapter.parse_dependencies(npm_files("v3-scoped"))

    def test_keeps_the_scope_as_part_of_the_package_name(self, graph):
        assert graph.nodes["pkg:npm/%40babel/core@7.24.0"].name == "@babel/core"

    def test_percent_encodes_the_scope_in_the_purl(self, graph):
        assert "pkg:npm/%40types/node@20.11.30" in graph.nodes

    def test_links_a_scoped_dependency_to_its_scoped_parent(self, graph):
        assert "pkg:npm/%40babel/parser@7.24.0" in edges_from(graph, "pkg:npm/%40babel/core@7.24.0")

    def test_resolves_a_scoped_package_nested_under_an_unscoped_one(self, graph):
        assert "pkg:npm/%40scope/util@2.1.0" in edges_from(graph, "pkg:npm/tool@1.0.0")

    def test_marks_a_scoped_dev_dependency_as_both_direct_and_dev(self, graph):
        node = graph.nodes["pkg:npm/%40types/node@20.11.30"]

        assert (node.is_direct, node.is_dev) == (True, True)


class TestParseLockfileVersion2:
    @pytest.fixture
    def graph(self, adapter):
        return adapter.parse_dependencies(npm_files("v2-basic"))

    def test_reads_the_packages_map_and_ignores_the_legacy_tree(self, graph):
        assert names_of(graph) == {"jsonwebtoken", "lodash", "ms", "semver", "typescript"}

    def test_follows_optional_dependencies(self, graph):
        assert "pkg:npm/ms@2.1.3" in edges_from(graph, "pkg:npm/jsonwebtoken@8.5.1")

    def test_follows_peer_dependencies(self, graph):
        assert "pkg:npm/typescript@5.4.3" in edges_from(graph, "pkg:npm/jsonwebtoken@8.5.1")

    def test_a_package_can_be_both_a_direct_dev_dependency_and_a_transitive_peer(self, graph):
        assert graph.nodes["pkg:npm/typescript@5.4.3"].is_direct is True


class TestWorkspacesAndLinks:
    @pytest.fixture
    def graph(self, adapter):
        return adapter.parse_dependencies(npm_files("v3-workspace-links"))

    def test_skips_symlink_entries_that_have_no_version_of_their_own(self, graph):
        assert names_of(graph) == {"lodash"}

    def test_skips_workspace_member_entries_outside_node_modules(self, graph):
        assert all("packages/" not in purl for purl in graph.nodes)


class TestRejectedInput:
    def test_refuses_a_version_1_lockfile_rather_than_guessing(self, adapter):
        with pytest.raises(UnsupportedLockfileError, match="lockfileVersion 1"):
            adapter.parse_dependencies(npm_files("v1-legacy"))

    def test_refuses_a_lockfile_that_is_not_valid_json(self, adapter):
        with pytest.raises(UnsupportedLockfileError):
            adapter.parse_dependencies({"package.json": "{}", "package-lock.json": "{not json"})

    def test_refuses_to_parse_when_the_lockfile_is_missing(self, adapter):
        with pytest.raises(UnsupportedLockfileError, match=r"package-lock\.json"):
            adapter.parse_dependencies({"package.json": "{}"})

    def test_refuses_a_lockfile_with_no_packages_map(self, adapter):
        with pytest.raises(UnsupportedLockfileError):
            adapter.parse_dependencies(
                {"package.json": "{}", "package-lock.json": '{"lockfileVersion": 3}'}
            )


class TestManifestPaths:
    def test_recognises_the_files_it_owns(self, adapter):
        assert adapter.is_manifest_path("package.json") is True
        assert adapter.is_manifest_path("package-lock.json") is True

    def test_does_not_claim_application_source_files(self, adapter):
        assert adapter.is_manifest_path("src/index.ts") is False

    def test_does_not_claim_a_manifest_belonging_to_a_vendored_dependency(self, adapter):
        assert adapter.is_manifest_path("node_modules/lodash/package.json") is False

    def test_offers_hints_the_repair_prompt_can_use(self, adapter):
        assert adapter.ci_hints()
