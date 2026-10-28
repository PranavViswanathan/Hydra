import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { AgentPanel } from '../components/AgentPanel'
import {
  AgentStateBadge,
  Button,
  Empty,
  ExposureStrip,
  Mono,
  Section,
  SeverityBadge,
  Sheet,
  StripLegend,
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
  countsOf,
  isTerminal,
  openCount,
  type DependencyEdge,
  type Severity,
  type Vulnerability,
  type VulnStatus,
} from '../lib/types'

type Filter = 'open' | 'all' | Severity

const STATUS_STYLE: Record<VulnStatus, string> = {
  open: 'text-graphite',
  in_progress: 'text-verdigris',
  fixed: 'text-verdigris',
  ignored: 'text-lichen',
  unfixable: 'text-lichen',
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
    <div className="space-y-12">
      <header>
        <Link to="/" className="text-[14px] text-lichen hover:text-graphite">
          Repositories
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="text-[26px] leading-[1.1] font-[650] tracking-[-0.015em] break-words font-stretch-[125%] sm:text-[40px]">
              {repo.full_name}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
              <AgentStateBadge state={repo.agent_state} />
              <span className="text-[14px] text-lichen">
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
        </div>

        <div className="mt-8">
          <ExposureStrip counts={countsOf(repo)} label={`Open in ${repo.full_name}`} />
          <StripLegend counts={countsOf(repo)} />
        </div>
      </header>

      {repo.config_error && (
        <div className="rounded-md border-l-4 border-critical bg-critical/8 px-5 py-4">
          <p className="font-semibold text-critical">
            The agent is paused: .vulnagent.yml could not be read
          </p>
          <p className="mt-1 font-mono text-[12.5px] text-graphite">{repo.config_error}</p>
        </div>
      )}

      <AgentPanel run={activeRun} />

      <Section
        title="Vulnerabilities"
        right={
          <div className="flex flex-wrap gap-0.5 rounded bg-sheet p-0.5 ring-1 ring-rule">
            {(['open', 'all', ...SEVERITIES] as Filter[]).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={filter === option}
                onClick={() => setFilter(option)}
                className={`rounded-[3px] px-2.5 py-1 text-[13px] transition-colors ${
                  filter === option
                    ? 'bg-graphite text-sheet'
                    : 'text-lichen hover:text-graphite'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        }
      >
        <Sheet>
          {shown.length === 0 ? (
            <Empty title="Nothing to show for this filter." />
          ) : (
            <table className="w-full min-w-[760px] text-left text-[14px]">
              <thead>
                <tr className="border-b border-rule text-[13px] text-lichen">
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
        </Sheet>
      </Section>

      <Section title="Past runs">
        <Sheet>
          {runs.length === 0 ? (
            <Empty title="The agent has not run on this repository yet." />
          ) : (
            <table className="w-full text-left text-[14px]">
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-rule last:border-0">
                    <td className="px-5 py-3 font-semibold">{runLabel(run.state)}</td>
                    <td className="px-3 py-3 text-lichen">
                      {run.trigger === 'manual' ? 'started by hand' : 'started automatically'}
                    </td>
                    <td className="px-3 py-3 text-lichen">{relativeTime(run.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      {run.pr_url && (
                        <a
                          href={run.pr_url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-mono text-[12.5px] text-verdigris font-stretch-[87.5%] hover:underline"
                        >
                          #{run.pr_number}
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Sheet>
      </Section>
    </div>
  )
}

function VulnRow({ vuln, edges }: { vuln: Vulnerability; edges: DependencyEdge[] }) {
  const [showPath, setShowPath] = useState(false)
  const path = useMemo(() => (showPath ? pathToRoot(edges, vuln.purl) : []), [showPath, edges, vuln.purl])

  return (
    <>
      <tr className="border-b border-rule last:border-0 hover:bg-ground/50">
        <td className="px-5 py-3">
          <a
            href={`https://osv.dev/vulnerability/${vuln.osv_id}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-[12.5px] text-verdigris font-stretch-[87.5%] hover:underline"
          >
            {vuln.osv_id}
          </a>
          {vuln.aliases && vuln.aliases.length > 0 && (
            <span className="mt-0.5 block font-mono text-[11.5px] text-lichen font-stretch-[87.5%]">
              {vuln.aliases.join(', ')}
            </span>
          )}
        </td>
        <td className="px-3 py-3">
          <Mono>{vuln.package_name}</Mono>
          {vuln.is_direct ? (
            <span className="ml-2 text-[12px] text-lichen">direct</span>
          ) : (
            <button
              type="button"
              aria-expanded={showPath}
              onClick={() => setShowPath((shown) => !shown)}
              className="ml-2 text-[12px] text-verdigris underline decoration-verdigris/40 underline-offset-2 hover:decoration-verdigris"
            >
              {showPath ? 'hide path' : 'transitive'}
            </button>
          )}
        </td>
        <td className="px-3 py-3 whitespace-nowrap">
          <Mono>{vuln.installed_version}</Mono>
          <span className="mx-1.5 text-faint" aria-label="to">
            →
          </span>
          {vuln.fixed_version ? (
            <Mono>{vuln.fixed_version}</Mono>
          ) : (
            <span className="text-lichen">no fix</span>
          )}
        </td>
        <td className="px-3 py-3">
          <SeverityBadge severity={vuln.severity} />
        </td>
        <td className={`px-3 py-3 ${STATUS_STYLE[vuln.status]}`}>{STATUS_LABEL[vuln.status]}</td>
      </tr>
      {showPath && (
        <tr className="border-b border-rule bg-ground/60">
          <td colSpan={5} className="px-5 py-3">
            {path.length === 0 ? (
              <span className="text-[14px] text-lichen">No recorded path to the root.</span>
            ) : (
              <ol className="flex flex-wrap items-center gap-2 font-mono text-[12px] font-stretch-[87.5%]">
                {path.map((step, index) => (
                  <li key={`${step}-${index}`} className="flex items-center gap-2">
                    {index > 0 && (
                      <span className="text-faint" aria-hidden>
                        →
                      </span>
                    )}
                    <span
                      className={
                        step === 'ROOT'
                          ? 'font-sans text-[13px] text-lichen'
                          : index === path.length - 1
                            ? 'text-critical'
                            : 'text-graphite'
                      }
                    >
                      {step === 'ROOT' ? 'your package.json' : prettyPurl(step)}
                    </span>
                  </li>
                ))}
              </ol>
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
