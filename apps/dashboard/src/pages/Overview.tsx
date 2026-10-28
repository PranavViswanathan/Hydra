import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AgentStateBadge,
  Button,
  Empty,
  ExposureStrip,
  Section,
  SeverityBadge,
  Sheet,
  StripLegend,
  relativeTime,
} from '../components/primitives'
import { useFixNow, useRepos, useScanNow } from '../hooks/useData'
import { installUrl } from '../lib/appwrite'
import { SEVERITIES, countsOf, openCount, type Repo, type Severity } from '../lib/types'

const SAMPLE_CONFIG = `version: 1
enabled: true
ecosystems: auto

scan:
  schedule: "0 6 * * *"
  on_push: true
  on_new_advisory: true

agent:
  auto_start: true
  severity_threshold: high
  max_ci_retries: 3
  auto_merge: false
  allow_major_bumps: false
`

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

function agentSentence(repos: Repo[]): string {
  const working = repos.find((repo) => repo.agent_state === 'working')
  if (working) return `The agent is working on ${working.full_name}.`
  const scanning = repos.find((repo) => repo.agent_state === 'scanning')
  if (scanning) return `The agent is scanning ${scanning.full_name}.`
  const stuck = repos.find((repo) => repo.agent_state === 'error')
  if (stuck) return `The agent is asleep. ${stuck.full_name} needs attention.`
  return 'The agent is asleep.'
}

export function Overview() {
  const { data: repos = [], isLoading } = useRepos()

  const totals = useMemo(() => {
    const sum: Record<Severity, number> = {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      unknown: 0,
    }
    for (const repo of repos) {
      const counts = countsOf(repo)
      for (const severity of SEVERITIES) sum[severity] += counts[severity]
    }
    return sum
  }, [repos])

  const total = SEVERITIES.reduce((sum, severity) => sum + totals[severity], 0)
  const configured = repos.filter((repo) => repo.has_config)
  const unconfigured = repos.filter((repo) => !repo.has_config)
  const where = `across ${plural(repos.length, 'repository', 'repositories')}`

  return (
    <div className="space-y-12">
      <section>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <h1 className="text-[28px] leading-[1.05] font-[650] tracking-[-0.015em] font-stretch-[125%] sm:text-[40px]">
              {total === 0 ? 'Nothing open' : plural(total, 'open vulnerability', 'open vulnerabilities')}{' '}
              <span className="block">{where}</span>
            </h1>
            <p className="mt-3 text-[18px]">{agentSentence(repos)}</p>
          </div>
          <a
            href={installUrl()}
            target="_blank"
            rel="noreferrer"
            className="rounded bg-verdigris px-3 py-1.5 text-[14px] font-semibold text-on-verdigris transition-colors hover:bg-verdigris/85"
          >
            Install GitHub App
          </a>
        </div>

        <div className="mt-8">
          <ExposureStrip counts={totals} label="Open across all repositories" />
          <StripLegend counts={totals} />
        </div>
      </section>

      <Section title="Repositories">
        <Sheet>
          {isLoading ? (
            <Empty title="Loading…" />
          ) : configured.length === 0 ? (
            <Empty
              title="No configured repositories yet"
              hint="Install the GitHub App, then add a .vulnagent.yml to a repository."
            />
          ) : (
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b border-rule text-[13px] text-lichen">
                  <th className="px-5 py-2.5 font-medium">Repository</th>
                  <th className="w-[26%] px-3 py-2.5 font-medium">Open</th>
                  <th className="px-3 py-2.5 font-medium">Agent</th>
                  <th className="px-3 py-2.5 font-medium">Last scan</th>
                  <th className="px-5 py-2.5">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {configured.map((repo) => (
                  <RepoRow key={repo.id} repo={repo} />
                ))}
              </tbody>
            </table>
          )}
        </Sheet>
      </Section>

      {unconfigured.length > 0 && (
        <Section title="Not configured">
          <Sheet>
            <div className="divide-y divide-rule">
              {unconfigured.map((repo) => (
                <UnconfiguredRow key={repo.id} repo={repo} />
              ))}
            </div>
          </Sheet>
        </Section>
      )}
    </div>
  )
}

function RepoRow({ repo }: { repo: Repo }) {
  const scan = useScanNow()
  const fix = useFixNow()
  const counts = countsOf(repo)
  const total = openCount(repo)
  const working = repo.agent_state === 'working' || repo.agent_state === 'scanning'

  return (
    <tr className="border-b border-rule last:border-0 hover:bg-ground/50">
      <td className="px-5 py-3.5 align-top">
        <Link to={`/repos/${repo.id}`} className="font-semibold hover:text-verdigris">
          {repo.full_name}
        </Link>
        <div className="mt-1 flex items-center gap-2 text-[13px] text-lichen">
          {repo.ecosystems.map((ecosystem) => (
            <span key={ecosystem}>{ecosystem}</span>
          ))}
          {repo.config_error && <span className="text-critical">config error</span>}
        </div>
      </td>
      <td className="px-3 py-3.5 align-top">
        <div className="mt-2">
          <ExposureStrip counts={counts} label={`Open in ${repo.full_name}`} size="small" />
        </div>
        {total === 0 ? (
          <span className="mt-1.5 block text-[13px] text-verdigris">clear</span>
        ) : (
          <div className="mt-1.5 flex flex-wrap gap-x-3">
            {SEVERITIES.filter((severity) => counts[severity] > 0).map((severity) => (
              <SeverityBadge key={severity} severity={severity} count={counts[severity]} />
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-3.5 align-top">
        <AgentStateBadge state={repo.agent_state} />
      </td>
      <td className="px-3 py-3.5 align-top text-[14px] text-lichen">
        {relativeTime(repo.last_scan_at)}
      </td>
      <td className="px-5 py-3 align-top">
        <div className="flex justify-end gap-2">
          <Button onClick={() => scan.mutate(repo.id)} disabled={working}>
            Scan now
          </Button>
          <Button
            variant="primary"
            onClick={() => fix.mutate(repo.id)}
            disabled={working || total === 0}
            title={total === 0 ? 'Nothing to fix' : undefined}
          >
            Fix now
          </Button>
        </div>
      </td>
    </tr>
  )
}

function UnconfiguredRow({ repo }: { repo: Repo }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(SAMPLE_CONFIG)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
      <div>
        <p className="font-semibold">{repo.full_name}</p>
        <p className="mt-0.5 text-[14px] text-lichen">
          Add a <code className="font-mono text-[12.5px] text-graphite">.vulnagent.yml</code> to
          the repository root to let the agent work on it.
        </p>
      </div>
      <Button onClick={copy}>{copied ? 'Copied' : 'Copy sample config'}</Button>
    </div>
  )
}
