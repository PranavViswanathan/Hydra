import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AgentStateBadge,
  Button,
  Card,
  CardHeader,
  Empty,
  SeverityBadge,
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

  const configured = repos.filter((repo) => repo.has_config)
  const unconfigured = repos.filter((repo) => !repo.has_config)

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Open vulnerabilities</h1>
          <p className="mt-1 text-sm text-ink-400">
            Across {repos.length} linked {repos.length === 1 ? 'repository' : 'repositories'}
          </p>
        </div>
        <a
          href={installUrl()}
          target="_blank"
          rel="noreferrer"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-ink-950 transition-colors hover:bg-accent/85"
        >
          Install GitHub App
        </a>
      </section>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {SEVERITIES.map((severity) => (
          <Card key={severity} className="px-4 py-3">
            <p className="font-mono text-2xl tabular-nums">{totals[severity]}</p>
            <p className="mt-1 text-xs tracking-wide text-ink-400 uppercase">{severity}</p>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader title="Repositories" />
        {isLoading ? (
          <Empty title="Loading…" />
        ) : configured.length === 0 ? (
          <Empty
            title="No configured repositories yet"
            hint="Install the GitHub App, then add a .vulnagent.yml to a repository."
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-xs tracking-wide text-ink-400 uppercase">
                <th className="px-5 py-2.5 font-medium">Repository</th>
                <th className="px-3 py-2.5 font-medium">Open</th>
                <th className="px-3 py-2.5 font-medium">Agent</th>
                <th className="px-3 py-2.5 font-medium">Last scan</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {configured.map((repo) => (
                <RepoRow key={repo.id} repo={repo} />
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {unconfigured.length > 0 && (
        <Card>
          <CardHeader title="Not configured" />
          <div className="divide-y divide-ink-800">
            {unconfigured.map((repo) => (
              <UnconfiguredRow key={repo.id} repo={repo} />
            ))}
          </div>
        </Card>
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
    <tr className="border-b border-ink-800/60 last:border-0 hover:bg-ink-850/40">
      <td className="px-5 py-3">
        <Link to={`/repos/${repo.id}`} className="font-medium hover:text-accent">
          {repo.full_name}
        </Link>
        <div className="mt-1 flex items-center gap-1.5">
          {repo.ecosystems.map((ecosystem) => (
            <span
              key={ecosystem}
              className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[11px] text-ink-400"
            >
              {ecosystem}
            </span>
          ))}
          {repo.config_error && (
            <span className="text-[11px] text-critical">config error</span>
          )}
        </div>
      </td>
      <td className="px-3 py-3">
        {total === 0 ? (
          <span className="text-sm text-good">clear</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {SEVERITIES.filter((severity) => counts[severity] > 0).map((severity) => (
              <SeverityBadge key={severity} severity={severity} count={counts[severity]} />
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-3">
        <AgentStateBadge state={repo.agent_state} />
      </td>
      <td className="px-3 py-3 text-ink-400">{relativeTime(repo.last_scan_at)}</td>
      <td className="px-5 py-3">
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
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
      <div>
        <p className="font-medium">{repo.full_name}</p>
        <p className="mt-0.5 text-sm text-ink-400">
          Add a <code className="font-mono text-ink-200">.vulnagent.yml</code> to the repository
          root to let the agent work on it.
        </p>
      </div>
      <Button onClick={copy}>{copied ? 'Copied' : 'Copy sample config'}</Button>
    </div>
  )
}
