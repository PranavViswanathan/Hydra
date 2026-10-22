"""Scan one repository end to end (§10, `scan_repo`).

Fetch the manifests, build the dependency graph, ask OSV what is affected,
cache the advisories, then reconcile the rows and update the counts.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from vulnagent.adapters import detect_adapters
from vulnagent.config.schema import RepoConfig, parse_repo_config
from vulnagent.core.adapter import EcosystemAdapter
from vulnagent.core.errors import VulnAgentError
from vulnagent.core.models import DepGraph, Severity, VulnFinding
from vulnagent.core.purl import parse_purl
from vulnagent.db.repositories import Database
from vulnagent.db.rows import (
    AdvisoryRow,
    DependencyEdge,
    Repo,
    RepoPackage,
    Scan,
    ScanTrigger,
)
from vulnagent.github.client import GitHubClient, Repository
from vulnagent.osv.client import OsvClient, PackageQuery
from vulnagent.osv.fixes import affected_versions_fixed_in
from vulnagent.osv.models import advisory_from_osv
from vulnagent.scanning.reconcile import reconcile, severity_counts


@dataclass(frozen=True, slots=True)
class ScanResult:
    scan_id: str
    packages_scanned: int
    vulns_found: int
    new_vulns: int
    worst_new_severity: Severity
    counts: dict[Severity, int]


class RepoScanner:
    def __init__(
        self,
        *,
        db: Database,
        github: GitHubClient,
        osv: OsvClient,
        now: dt.datetime | None = None,
    ) -> None:
        self._db = db
        self._github = github
        self._osv = osv
        self._now = now or dt.datetime.now(dt.UTC)

    def scan(self, repo: Repo, *, trigger: ScanTrigger) -> ScanResult:
        scan = self._db.scans.create(Scan(repo_id=repo.id, trigger=trigger, started_at=self._now))
        try:
            result = self._run(repo, scan.id)
        except Exception as error:
            self._db.scans.update(
                scan.id,
                {"status": "failed", "error": str(error)[:500], "finished_at": self._now},
            )
            raise
        self._db.scans.update(
            scan.id,
            {
                "status": "succeeded",
                "packages_scanned": result.packages_scanned,
                "vulns_found": result.vulns_found,
                "finished_at": self._now,
            },
        )
        return result

    def _run(self, repo: Repo, scan_id: str) -> ScanResult:
        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        commit_sha = self._github.head_sha(target, repo.default_branch)

        adapters = detect_adapters(
            self._github.list_root_paths(target, repo.default_branch), config.ecosystems
        )
        if not adapters:
            raise VulnAgentError("no supported ecosystem found in the repository root")

        graphs = [
            (adapter, adapter.parse_dependencies(self._fetch_manifests(target, adapter, repo)))
            for adapter in adapters
        ]

        self._save_graph(repo.id, scan_id, graphs)
        findings = self._find_vulnerabilities(graphs)
        return self._reconcile(repo, scan_id, graphs, findings, config, commit_sha)

    def _fetch_manifests(
        self, target: Repository, adapter: EcosystemAdapter, repo: Repo
    ) -> dict[str, str]:
        return self._github.get_files(target, adapter.manifest_files, repo.default_branch)

    def _save_graph(
        self, repo_id: str, scan_id: str, graphs: list[tuple[EcosystemAdapter, DepGraph]]
    ) -> None:
        """Replace the snapshot: rows not seen in this scan are deleted (§7.4)."""
        for existing in self._db.packages.for_repo(repo_id):
            self._db.packages.delete(existing.id)
        for existing_edge in self._db.edges.for_repo(repo_id):
            self._db.edges.delete(existing_edge.id)

        for adapter, graph in graphs:
            for node in graph.nodes.values():
                self._db.packages.create(
                    RepoPackage(
                        repo_id=repo_id,
                        purl=node.purl,
                        ecosystem=adapter.id,
                        name=node.name,
                        version=node.version,
                        is_direct=node.is_direct,
                        is_dev=node.is_dev,
                        scan_id=scan_id,
                    )
                )
            for edge in graph.edges:
                self._db.edges.create(
                    DependencyEdge(
                        repo_id=repo_id,
                        parent_purl=str(edge.parent),
                        child_purl=edge.child,
                        requested_range=edge.requested_range,
                        ecosystem=adapter.id,
                        scan_id=scan_id,
                    )
                )

    def _find_vulnerabilities(
        self, graphs: list[tuple[EcosystemAdapter, DepGraph]]
    ) -> list[VulnFinding]:
        queries: list[PackageQuery] = []
        ecosystem_of: dict[str, str] = {}
        for adapter, graph in graphs:
            for node in graph.nodes.values():
                queries.append(
                    PackageQuery(
                        name=node.name, ecosystem=adapter.osv_ecosystem, version=node.version
                    )
                )
                ecosystem_of[node.purl] = adapter.osv_ecosystem

        affected = self._osv.query_batch(queries)
        advisories = self._advisories_for(sorted({id_ for ids in affected.values() for id_ in ids}))

        findings: list[VulnFinding] = []
        for purl, osv_ids in affected.items():
            _, name, _ = parse_purl(purl)
            for osv_id in osv_ids:
                advisory = advisories.get(osv_id)
                if advisory is None:
                    continue
                findings.append(
                    VulnFinding(
                        osv_id=osv_id,
                        aliases=advisory.aliases,
                        purl=purl,
                        fixed_versions=affected_versions_fixed_in(
                            json.loads(advisory.affected_json or "{}"),
                            name,
                            ecosystem_of.get(purl, "npm"),
                        ),
                        severity=advisory.severity,
                    )
                )
        return findings

    def _advisories_for(self, osv_ids: list[str]) -> dict[str, AdvisoryRow]:
        known = self._db.advisories.known_ids(osv_ids)
        for osv_id in osv_ids:
            if osv_id in known:
                continue
            raw = self._osv.get_vulnerability(osv_id)
            if raw is None:
                continue
            advisory = advisory_from_osv(raw)
            known[osv_id] = self._db.advisories.create(
                AdvisoryRow(
                    osv_id=advisory.osv_id,
                    aliases=advisory.aliases,
                    summary=advisory.summary,
                    details=advisory.details,
                    severity=advisory.severity,
                    cvss_score=advisory.cvss_score,
                    affected_json=json.dumps({"affected": advisory.affected}),
                    osv_modified=advisory.osv_modified,
                )
            )
        return known

    def _reconcile(
        self,
        repo: Repo,
        scan_id: str,
        graphs: list[tuple[EcosystemAdapter, DepGraph]],
        findings: list[VulnFinding],
        config: RepoConfig,
        commit_sha: str,
    ) -> ScanResult:
        nodes = {purl: node for _, graph in graphs for purl, node in graph.nodes.items()}
        outcome = reconcile(
            repo_id=repo.id,
            existing=self._db.vulnerabilities.for_repo(repo.id),
            found=findings,
            package_names={purl: node.name for purl, node in nodes.items()},
            installed_versions={purl: node.version for purl, node in nodes.items()},
            direct_purls={purl for purl, node in nodes.items() if node.is_direct},
            ignored={rule.id for rule in config.agent.ignore if rule.applies_on(self._now.date())},
            now=self._now,
        )

        for row in outcome.created:
            self._db.vulnerabilities.create(row)
        for row_id, changes in outcome.still_present:
            self._db.vulnerabilities.update(row_id, changes)
        for row_id in outcome.resolved:
            self._db.vulnerabilities.update(row_id, {"status": "fixed", "resolved_at": self._now})

        counts = severity_counts(self._db.vulnerabilities.for_repo(repo.id))
        self._db.repos.set_counts(repo.id, counts)
        self._db.repos.update(
            repo.id,
            {"last_scan_at": self._now, "ecosystems": [adapter.id for adapter, _ in graphs]},
        )

        worst = _worst_of(outcome.created)
        return ScanResult(
            scan_id=scan_id,
            packages_scanned=len(nodes),
            vulns_found=len(findings),
            new_vulns=outcome.new_count,
            worst_new_severity=worst,
            counts=counts,
        )


def _config_of(repo: Repo) -> RepoConfig:
    if not repo.config_json:
        return RepoConfig()
    return parse_repo_config(repo.config_json, path=".vulnagent.yml")


def _worst_of(created: list[Any]) -> Severity:
    from vulnagent.core.models import severity_rank

    if not created:
        return "unknown"
    worst: Severity = max((row.severity for row in created), key=severity_rank)
    return worst
