import pytest

from vulnagent.osv.severity import cvss_score_of, severity_of


def advisory(**fields) -> dict:
    return {"id": "GHSA-test", **fields}


class TestSeverityFromGitHubsOwnRating:
    @pytest.mark.parametrize(
        ("rating", "expected"),
        [
            ("LOW", "low"),
            ("MODERATE", "medium"),
            ("HIGH", "high"),
            ("CRITICAL", "critical"),
        ],
    )
    def test_maps_a_github_severity_onto_the_internal_scale(self, rating, expected):
        assert severity_of(advisory(database_specific={"severity": rating})) == expected

    def test_accepts_a_rating_in_any_casing(self):
        assert severity_of(advisory(database_specific={"severity": "moderate"})) == "medium"

    def test_prefers_the_published_rating_over_the_cvss_vector(self):
        raw = advisory(
            database_specific={"severity": "LOW"},
            severity=[{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        )

        assert severity_of(raw) == "low"

    def test_falls_through_to_the_vector_when_the_rating_is_not_one_it_knows(self):
        raw = advisory(
            database_specific={"severity": "SPICY"},
            severity=[{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        )

        assert severity_of(raw) == "critical"


class TestSeverityFromCvssVector:
    @pytest.mark.parametrize(
        ("vector", "expected"),
        [
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "critical"),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", "high"),
            ("CVSS:3.1/AV:N/AC:H/PR:L/UI:R/S:U/C:L/I:N/A:N", "low"),
        ],
    )
    def test_derives_severity_from_the_computed_base_score(self, vector, expected):
        assert severity_of(advisory(severity=[{"type": "CVSS_V3", "score": vector}])) == expected

    def test_reads_a_cvss_v4_vector(self):
        raw = advisory(
            severity=[
                {
                    "type": "CVSS_V4",
                    "score": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",
                }
            ]
        )

        assert severity_of(raw) == "critical"

    def test_exposes_the_numeric_base_score_alongside_the_band(self):
        raw = advisory(
            severity=[{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
        )

        assert cvss_score_of(raw) == pytest.approx(9.8)

    def test_prefers_the_highest_version_vector_when_several_are_published(self):
        raw = advisory(
            severity=[
                {"type": "CVSS_V2", "score": "AV:N/AC:L/Au:N/C:P/I:P/A:P"},
                {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"},
            ]
        )

        assert cvss_score_of(raw) == pytest.approx(9.8)


class TestMissingOrUnusableData:
    def test_an_advisory_with_no_severity_information_is_unknown(self):
        assert severity_of(advisory()) == "unknown"

    def test_a_malformed_vector_does_not_raise(self):
        assert (
            severity_of(advisory(severity=[{"type": "CVSS_V3", "score": "nonsense"}])) == "unknown"
        )

    def test_an_advisory_with_no_severity_information_has_no_score(self):
        assert cvss_score_of(advisory()) is None

    def test_a_severity_list_of_an_unexpected_shape_is_ignored(self):
        assert severity_of(advisory(severity="HIGH")) == "unknown"

    def test_a_zero_base_score_is_reported_as_unknown_rather_than_low(self):
        raw = advisory(
            severity=[{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N"}]
        )

        assert severity_of(raw) == "unknown"
