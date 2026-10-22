import datetime as dt

from vulnagent.core.models import VulnFinding
from vulnagent.db.rows import Vulnerability
from vulnagent.scanning.reconcile import reconcile, severity_counts, worst_severity

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)
EARLIER = NOW - dt.timedelta(days=7)
LODASH = "pkg:npm/lodash@4.17.20"
QS = "pkg:npm/qs@6.5.2"


def finding(purl=LODASH, osv_id="GHSA-a", fixed=("4.17.21",), severity="high") -> VulnFinding:
    return VulnFinding(osv_id=osv_id, purl=purl, fixed_versions=list(fixed), severity=severity)


def existing_row(purl=LODASH, osv_id="GHSA-a", status="open", severity="high", row_id="v1"):
    return Vulnerability(
        **{
            "$id": row_id,
            "repo_id": "repo1",
            "osv_id": osv_id,
            "purl": purl,
            "package_name": "lodash",
            "installed_version": "4.17.20",
            "severity": severity,
            "status": status,
            "first_seen_at": EARLIER,
            "last_seen_at": EARLIER,
        }
    )


def run(existing=(), found=(), ignored=(), direct=(LODASH,)):
    return reconcile(
        repo_id="repo1",
        existing=list(existing),
        found=list(found),
        package_names={LODASH: "lodash", QS: "qs"},
        installed_versions={LODASH: "4.17.20", QS: "6.5.2"},
        direct_purls=set(direct),
        ignored=set(ignored),
        now=NOW,
    )


class TestNewVulnerabilities:
    def test_a_vulnerability_not_seen_before_is_created(self):
        outcome = run(found=[finding()])

        assert outcome.new_count == 1
        assert outcome.created[0].osv_id == "GHSA-a"

    def test_a_new_vulnerability_starts_open(self):
        assert run(found=[finding()]).created[0].status == "open"

    def test_records_the_version_installed_and_the_one_that_fixes_it(self):
        created = run(found=[finding()]).created[0]

        assert (created.installed_version, created.fixed_version) == ("4.17.20", "4.17.21")

    def test_an_advisory_with_no_fix_is_recorded_as_unfixable(self):
        created = run(found=[finding(fixed=())]).created[0]

        assert created.status == "unfixable"
        assert created.fixed_version is None

    def test_knows_whether_the_package_is_a_direct_dependency(self):
        outcome = run(found=[finding(), finding(purl=QS, osv_id="GHSA-b")], direct=(LODASH,))

        by_id = {row.osv_id: row for row in outcome.created}
        assert by_id["GHSA-a"].is_direct is True
        assert by_id["GHSA-b"].is_direct is False

    def test_an_ignored_advisory_is_recorded_but_not_open(self):
        created = run(found=[finding()], ignored=["GHSA-a"]).created[0]

        assert created.status == "ignored"

    def test_timestamps_both_sightings_on_first_discovery(self):
        created = run(found=[finding()]).created[0]

        assert created.first_seen_at == created.last_seen_at == NOW


class TestVulnerabilitiesThatAreStillThere:
    def test_an_unchanged_vulnerability_is_not_recreated(self):
        outcome = run(existing=[existing_row()], found=[finding()])

        assert outcome.created == []
        assert len(outcome.still_present) == 1

    def test_the_last_seen_timestamp_moves_forward(self):
        _, changes = run(existing=[existing_row()], found=[finding()]).still_present[0]

        assert changes["last_seen_at"] == NOW

    def test_the_first_seen_timestamp_is_left_alone(self):
        _, changes = run(existing=[existing_row()], found=[finding()]).still_present[0]

        assert "first_seen_at" not in changes

    def test_a_reassessed_severity_is_written_back(self):
        _, changes = run(
            existing=[existing_row(severity="medium")], found=[finding(severity="critical")]
        ).still_present[0]

        assert changes["severity"] == "critical"

    def test_a_vulnerability_the_agent_is_working_on_stays_in_progress(self):
        _, changes = run(
            existing=[existing_row(status="in_progress")], found=[finding()]
        ).still_present[0]

        assert "status" not in changes

    def test_an_ignored_vulnerability_is_not_reopened_by_a_scan(self):
        _, changes = run(
            existing=[existing_row(status="ignored")], found=[finding()]
        ).still_present[0]

        assert "status" not in changes

    def test_a_vulnerability_newly_added_to_the_ignore_list_becomes_ignored(self):
        _, changes = run(
            existing=[existing_row(status="open")], found=[finding()], ignored=["GHSA-a"]
        ).still_present[0]

        assert changes["status"] == "ignored"


class TestVulnerabilitiesThatAreGone:
    def test_a_vulnerability_no_longer_present_is_resolved(self):
        outcome = run(existing=[existing_row()], found=[])

        assert outcome.resolved == ["v1"]

    def test_an_already_fixed_row_is_not_resolved_twice(self):
        outcome = run(existing=[existing_row(status="fixed")], found=[])

        assert outcome.resolved == []

    def test_an_ignored_row_is_not_resolved_just_because_it_is_ignored(self):
        outcome = run(existing=[existing_row(status="ignored")], found=[])

        assert outcome.resolved == []

    def test_the_same_advisory_on_a_different_package_version_is_a_different_row(self):
        outcome = run(existing=[existing_row(purl=LODASH)], found=[finding(purl=QS)])

        assert outcome.resolved == ["v1"]
        assert outcome.new_count == 1

    def test_an_unfixable_vulnerability_that_disappears_is_resolved(self):
        outcome = run(existing=[existing_row(status="unfixable")], found=[])

        assert outcome.resolved == ["v1"]


class TestCounts:
    def test_counts_open_vulnerabilities_by_severity(self):
        rows = [
            existing_row(severity="critical", row_id="a"),
            existing_row(severity="high", row_id="b"),
            existing_row(severity="high", row_id="c"),
        ]

        assert severity_counts(rows) == {
            "critical": 1,
            "high": 2,
            "medium": 0,
            "low": 0,
            "unknown": 0,
        }

    def test_a_vulnerability_being_worked_on_still_counts_as_open(self):
        assert severity_counts([existing_row(status="in_progress")])["high"] == 1

    def test_fixed_and_ignored_vulnerabilities_do_not_count(self):
        rows = [
            existing_row(status="fixed", row_id="a"),
            existing_row(status="ignored", row_id="b"),
        ]

        assert sum(severity_counts(rows).values()) == 0

    def test_every_severity_appears_even_at_zero(self):
        assert set(severity_counts([])) == {"critical", "high", "medium", "low", "unknown"}


class TestWorstSeverity:
    def test_picks_the_most_serious_finding(self):
        findings = [finding(severity="low"), finding(severity="critical"), finding(severity="high")]

        assert worst_severity(findings) == "critical"

    def test_nothing_found_is_unknown(self):
        assert worst_severity([]) == "unknown"
