import pytest

from vulnagent.core.purl import PurlError, make_purl, parse_purl


def test_builds_purl_for_plain_package():
    assert make_purl("npm", "lodash", "4.17.20") == "pkg:npm/lodash@4.17.20"


def test_percent_encodes_the_at_sign_of_a_scoped_npm_package():
    assert make_purl("npm", "@babel/core", "7.24.0") == "pkg:npm/%40babel/core@7.24.0"


def test_parses_plain_purl_back_into_its_parts():
    assert parse_purl("pkg:npm/lodash@4.17.20") == ("npm", "lodash", "4.17.20")


def test_parses_scoped_purl_back_into_the_original_package_name():
    assert parse_purl("pkg:npm/%40babel/core@7.24.0") == ("npm", "@babel/core", "7.24.0")


def test_round_trips_names_that_contain_dots_and_dashes():
    purl = make_purl("npm", "@types/node-fetch", "2.6.11")
    assert parse_purl(purl) == ("npm", "@types/node-fetch", "2.6.11")


def test_preserves_prerelease_and_build_metadata_in_the_version():
    purl = make_purl("npm", "vite", "5.0.0-beta.1")
    assert parse_purl(purl) == ("npm", "vite", "5.0.0-beta.1")


def test_uses_the_ecosystem_it_is_given():
    assert make_purl("pypi", "requests", "2.31.0") == "pkg:pypi/requests@2.31.0"


@pytest.mark.parametrize(
    "bad",
    [
        "lodash@4.17.20",
        "pkg:npm/lodash",
        "pkg:/lodash@1.0.0",
        "pkg:npm/@1.0.0",
        "",
    ],
)
def test_rejects_strings_that_are_not_well_formed_purls(bad):
    with pytest.raises(PurlError):
        parse_purl(bad)


def test_rejects_building_a_purl_without_a_version():
    with pytest.raises(PurlError):
        make_purl("npm", "lodash", "")
