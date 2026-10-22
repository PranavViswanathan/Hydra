import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { AgentPanel } from '../components/AgentPanel'
import {
  AgentStateBadge,
  Button,
  Card,
  CardHeader,
  Empty,
  Mono,
  SeverityBadge,
  relativeTime,
  runLabel,
} from '../components/primitives'
import {
  useEdges,
  useFixNow,
  useRepo,
  useRuns,
  useScanNow,
  useVulnerabilities,
} from '../hooks/useData'
import {
  SEVERITIES,
  isTerminal,
  openCount,
  type DependencyEdge,
  type Severity,
  type Vulnerability,
  type VulnStatus,
} from '../lib/types'

type Filter = 'open' | 'all' | Severity

const STATUS_STYLE: Record<VulnStatus, string> = {
  open: 'text-ink-200',
  in_progress: 'text-accent',
  fixed: 'text-good',
  ignored: 'text-ink-400',
  unfixable: 'text-ink-400',
  needs_major: 'text-high',
}

const STATUS_LABEL: Record<VulnStatus, string> = {
  open: 'open',
  in_progress: 'being fixed',
  fixed: 'fixed',
  ignored: 'ignored',
  unfixable: 'no fix available',
  needs_major: 'needs a major bump',
}

export function RepoDetail() {
  const { repoId = '' } = useParams()
  const { data: repo, isLoading } = useRepo(repoId)
  const { data: vulnerabilities = [] } = useVulnerabilities(repoId)
  const { data: runs = [] } = useRuns(repoId)
  const { data: edges = [] } = useEdges(repoId)
  const scan = useScanNow()
  const fix = useFixNow()
  const [filter, setFilter] = useState<Filter>('open')

  const shown = useMemo(() => {
    if (filter === 'all') return vulnerabilities
    if (filter === 'open') {
      return vulnerabilities.filter(
        (vuln) => vuln.status === 'open' || vuln.status === 'in_progress',
      )
    }
    return vulnerabilities.filter((vuln) => vuln.severity === filter)
  }, [vulnerabilities, filter])

  if (isLoading) return <Empty title="Loading…" />
  if (!repo) return <Empty title="That repository is not linked to your account." />

  const activeRun = runs.find((run) => !isTerminal(run.state)) ?? runs[0] ?? null
  const busy = repo.agent_state === 'working' || repo.agent_state === 'scanning'

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/" className="text-sm text-ink-400 hover:text-ink-200">
            ← All repositories
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{repo.full_name}</h1>
          <div className="mt-2 flex items-center gap-4">
            <AgentStateBadge state={repo.agent_state} />
            <span className="text-sm text-ink-400">
              last scanned {relativeTime(repo.last_scan_at)}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => scan.mutate(repo.id)} disabled={busy}>
            Scan now
          </Button>
          <Button
            variant="primary"
            onClick={() => fix.mutate(repo.id)}
            disabled={busy || openCount(repo) === 0}
          >
            Fix now
          </Button>
        </div>
      </header>

      {repo.config_error && (
        <Card className="border-critical/40 bg-critical/5 px-5 py-4">
          <p className="text-sm font-medium text-critical">
            The agent is paused: .vulnagent.yml could not be read
          </p>
          <p className="mt-1 font-mono text-[13px] text-ink-200">{repo.config_error}</p>
        </Card>
      )}

      <AgentPanel run={activeRun} />

      <Card>
        <CardHeader
          title="Vulnerabilities"
          right={
            <div className="flex gap-1">
              {(['open', 'all', ...SEVERITIES] as Filter[]).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setFilter(option)}
                  className={`rounded px-2 py-1 text-xs transition-colors ${
                    filter === option
                      ? 'bg-ink-700 text-ink-50'
                      : 'text-ink-400 hover:text-ink-200'
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          }
        />
        {shown.length === 0 ? (
          <Empty title="Nothing to show for this filter." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-xs tracking-wide text-ink-400 uppercase">
                <th className="px-5 py-2.5 font-medium">Advisory</th>
                <th className="px-3 py-2.5 font-medium">Package</th>
                <th className="px-3 py-2.5 font-medium">Installed → fixed</th>
                <th className="px-3 py-2.5 font-medium">Severity</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((vuln) => (
                <VulnRow key={vuln.id} vuln={vuln} edges={edges} />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card>
        <CardHeader title="Past runs" />
        {runs.length === 0 ? (
          <Empty title="The agent has not run on this repository yet." />
        ) : (
          <ul className="divide-y divide-ink-800">
            {runs.map((run) => (
              <li key={run.id} className="flex items-center justify-between px-5 py-3 text-sm">
                <div>
                  <span className="text-ink-200">{runLabel(run.state)}</span>
                  <span className="ml-2 text-ink-400">
                    {run.trigger === 'manual' ? 'started by hand' : 'started automatically'} ·{' '}
                    {relativeTime(run.created_at)}
                  </span>
                </div>
                {run.pr_url && (
                  <a
                    href={run.pr_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-mono text-[13px] text-accent hover:underline"
                  >
                    #{run.pr_number}
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function VulnRow({ vuln, edges }: { vuln: Vulnerability; edges: DependencyEdge[] }) {
  const [showPath, setShowPath] = useState(false)
  const path = useMemo(() => (showPath ? pathToRoot(edges, vuln.purl) : []), [showPath, edges, vuln.purl])

  return (
    <>
      <tr className="border-b border-ink-800/60 last:border-0 hover:bg-ink-850/40">
        <td className="px-5 py-3">
          <a
            href={`https://osv.dev/vulnerability/${vuln.osv_id}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-[13px] text-accent hover:underline"
          >
            {vuln.osv_id}
          </a>
          {vuln.aliases && vuln.aliases.length > 0 && (
            <span className="ml-2 font-mono text-[12px] text-ink-400">
              {vuln.aliases.join(', ')}
            </span>
          )}
        </td>
        <td className="px-3 py-3">
          <Mono>{vuln.package_name}</Mono>
          <button
            type="button"
            onClick={() => setShowPath((shown) => !shown)}
            className={`ml-2 text-[11px] ${vuln.is_direct ? 'text-ink-400' : 'text-accent hover:underline'}`}
          >
            {vuln.is_direct ? 'direct' : showPath ? 'hide path' : 'transitive'}
          </button>
        </td>
        <td className="px-3 py-3">
          <Mono>{vuln.installed_version}</Mono>
          <span className="mx-1.5 text-ink-600">→</span>
          {vuln.fixed_version ? (
            <Mono>{vuln.fixed_version}</Mono>
          ) : (
            <span className="text-ink-400">no fix</span>
          )}
        </td>
        <td className="px-3 py-3">
          <SeverityBadge severity={vuln.severity} />
        </td>
        <td className={`px-3 py-3 ${STATUS_STYLE[vuln.status]}`}>{STATUS_LABEL[vuln.status]}</td>
      </tr>
      {showPath && (
        <tr className="bg-ink-950/60">
          <td colSpan={5} className="px-5 py-3">
            {path.length === 0 ? (
              <span className="text-sm text-ink-400">No recorded path to the root.</span>
            ) : (
              <div className="flex flex-wrap items-center gap-2 font-mono text-[12px]">
                {path.map((step, index) => (
                  <span key={`${step}-${index}`} className="flex items-center gap-2">
                    {index > 0 && <span className="text-ink-600">→</span>}
                    <span
                      className={
                        step === 'ROOT'
                          ? 'rounded bg-ink-800 px-1.5 py-0.5 text-ink-400'
                          : 'text-ink-200'
                      }
                    >
                      {step === 'ROOT' ? 'your package.json' : prettyPurl(step)}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

/** Walk the recorded edges back to ROOT so a transitive finding explains itself. */
function pathToRoot(edges: DependencyEdge[], purl: string): string[] {
  const parents = new Map<string, string>()
  for (const edge of edges) {
    if (!parents.has(edge.child_purl)) parents.set(edge.child_purl, edge.parent_purl)
  }

  const path = [purl]
  const seen = new Set([purl])
  let current = purl

  while (parents.has(current)) {
    const parent = parents.get(current)
    if (parent === undefined || seen.has(parent)) break
    path.unshift(parent)
    seen.add(parent)
    if (parent === 'ROOT') break
    current = parent
  }
  return path[0] === 'ROOT' ? path : []
}

function prettyPurl(purl: string): string {
  return purl.replace('pkg:npm/', '').replace('%40', '@')
}
