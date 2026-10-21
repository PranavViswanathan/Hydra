from vulnagent.osv.fixes import affected_versions_fixed_in, is_version_affected


def affected(package_name="lodash", ecosystem="npm", **extra) -> dict:
    return {"package": {"name": package_name, "ecosystem": ecosystem}, **extra}


def semver_range(*events) -> dict:
    return {"type": "SEMVER", "events": list(events)}


class TestFixedVersions:
    def test_reads_the_fixed_version_from_a_semver_range(self):
        raw = {
            "affected": [affected(ranges=[semver_range({"introduced": "0"}, {"fixed": "4.17.21"})])]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_collects_every_fix_across_several_ranges_in_ascending_order(self):
        raw = {
            "affected": [
                affected(
                    ranges=[
                        semver_range({"introduced": "2.0.0"}, {"fixed": "2.1.4"}),
                        semver_range({"introduced": "0"}, {"fixed": "1.9.10"}),
                    ]
                )
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["1.9.10", "2.1.4"]

    def test_sorts_by_version_precedence_rather_than_alphabetically(self):
        raw = {
            "affected": [
                affected(
                    ranges=[
                        semver_range({"fixed": "1.10.0"}),
                        semver_range({"fixed": "1.2.0"}),
                        semver_range({"fixed": "1.9.0"}),
                    ]
                )
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["1.2.0", "1.9.0", "1.10.0"]

    def test_reads_an_ecosystem_typed_range_as_well_as_a_semver_one(self):
        raw = {
            "affected": [affected(ranges=[{"type": "ECOSYSTEM", "events": [{"fixed": "4.17.21"}]}])]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_ignores_git_ranges_whose_fixes_are_commit_hashes(self):
        raw = {
            "affected": [
                affected(
                    ranges=[
                        {"type": "GIT", "events": [{"fixed": "a" * 40}]},
                        semver_range({"fixed": "4.17.21"}),
                    ]
                )
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_ignores_entries_for_a_different_package(self):
        raw = {
            "affected": [
                affected("express", ranges=[semver_range({"fixed": "4.18.0"})]),
                affected("lodash", ranges=[semver_range({"fixed": "4.17.21"})]),
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_ignores_the_same_package_name_in_a_different_ecosystem(self):
        raw = {"affected": [affected("lodash", "PyPI", ranges=[semver_range({"fixed": "1.0.0"})])]}

        assert affected_versions_fixed_in(raw, "lodash", "npm") == []

    def test_matches_the_ecosystem_regardless_of_casing(self):
        raw = {"affected": [affected("lodash", "NPM", ranges=[semver_range({"fixed": "4.17.21"})])]}

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_an_advisory_with_no_fix_yields_nothing(self):
        raw = {"affected": [affected(ranges=[semver_range({"introduced": "0"})])]}

        assert affected_versions_fixed_in(raw, "lodash", "npm") == []

    def test_a_last_affected_bound_is_not_mistaken_for_a_fix(self):
        raw = {
            "affected": [
                affected(ranges=[semver_range({"introduced": "0"}, {"last_affected": "4.17.20"})])
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == []

    def test_deduplicates_a_fix_published_in_more_than_one_range(self):
        raw = {
            "affected": [
                affected(ranges=[semver_range({"fixed": "4.17.21"})]),
                affected(ranges=[semver_range({"fixed": "4.17.21"})]),
            ]
        }

        assert affected_versions_fixed_in(raw, "lodash", "npm") == ["4.17.21"]

    def test_an_advisory_with_no_affected_section_yields_nothing(self):
        assert affected_versions_fixed_in({}, "lodash", "npm") == []

    def test_a_scoped_package_name_is_matched_in_full(self):
        raw = {
            "affected": [affected("@babel/traverse", ranges=[semver_range({"fixed": "7.23.2"})])]
        }

        assert affected_versions_fixed_in(raw, "@babel/traverse", "npm") == ["7.23.2"]

    def test_discards_a_fix_that_is_not_a_usable_version_string(self):
        raw = {"affected": [affected(ranges=[semver_range({"fixed": "unreleased"})])]}

        assert affected_versions_fixed_in(raw, "lodash", "npm") == []


class TestVersionIsAffected:
    def test_a_version_below_the_fix_is_affected(self):
        raw = {
            "affected": [affected(ranges=[semver_range({"introduced": "0"}, {"fixed": "4.17.21"})])]
        }

        assert is_version_affected(raw, "lodash", "npm", "4.17.20") is True

    def test_the_fixed_version_itself_is_not_affected(self):
        raw = {
            "affected": [affected(ranges=[semver_range({"introduced": "0"}, {"fixed": "4.17.21"})])]
        }

        assert is_version_affected(raw, "lodash", "npm", "4.17.21") is False

    def test_a_version_below_the_introduced_bound_is_not_affected(self):
        raw = {
            "affected": [
                affected(ranges=[semver_range({"introduced": "4.0.0"}, {"fixed": "4.17.21"})])
            ]
        }

        assert is_version_affected(raw, "lodash", "npm", "3.10.1") is False

    def test_an_explicitly_listed_version_is_affected_even_without_ranges(self):
        raw = {"affected": [affected(versions=["4.17.20", "4.17.19"])]}

        assert is_version_affected(raw, "lodash", "npm", "4.17.20") is True

    def test_a_version_of_a_different_package_is_not_affected(self):
        raw = {"affected": [affected("express", ranges=[semver_range({"fixed": "4.18.0"})])]}

        assert is_version_affected(raw, "lodash", "npm", "4.17.20") is False
