/**
 * The demo data source.
 *
 * With no Appwrite project configured the dashboard runs against this instead,
 * so the whole interface, including a live agent run, can be seen before any
 * credentials exist. It also drives the timeline forward on a timer, which is
 * what Realtime does against a real project.
 */

import type { AgentEvent, AgentRun, DependencyEdge, Repo, Vulnerability } from './types'

type Listener = () => void

const ONE_MINUTE = 60_000

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * ONE_MINUTE).toISOString()
}

const REPOS: Repo[] = [
  {
    id: 'repo_test_app',
    full_name: 'pranav/vulnagent-test-app',
    default_branch: 'main',
    has_config: true,
    config_error: null,
    ecosystems: ['npm'],
    agent_state: 'idle',
    active_run_id: null,
    last_scan_at: minutesAgo(12),
    open_critical: 1,
    open_high: 2,
    open_medium: 1,
    open_low: 0,
    open_unknown: 0,
  },
  {
    id: 'repo_checkout',
    full_name: 'pranav/checkout-api',
    default_branch: 'main',
    has_config: true,
    config_error: null,
    ecosystems: ['npm'],
    agent_state: 'idle',
    active_run_id: null,
    last_scan_at: minutesAgo(140),
    open_critical: 0,
    open_high: 0,
    open_medium: 2,
    open_low: 3,
    open_unknown: 1,
  },
  {
    id: 'repo_docs',
    full_name: 'pranav/docs-site',
    default_branch: 'main',
    has_config: false,
    config_error: null,
    ecosystems: [],
    agent_state: 'idle',
    active_run_id: null,
    last_scan_at: null,
    open_critical: 0,
    open_high: 0,
    open_medium: 0,
    open_low: 0,
    open_unknown: 0,
  },
  {
    id: 'repo_legacy',
    full_name: 'pranav/legacy-worker',
    default_branch: 'master',
    has_config: true,
    config_error:
      '.vulnagent.yml: agent.max_ci_retries: Input should be less than or equal to 5',
    ecosystems: ['npm'],
    agent_state: 'error',
    active_run_id: null,
    last_scan_at: minutesAgo(2880),
    open_critical: 0,
    open_high: 1,
    open_medium: 0,
    open_low: 0,
    open_unknown: 2,
  },
]

const VULNERABILITIES: Vulnerability[] = [
  {
    id: 'v_jwt',
    repo_id: 'repo_test_app',
    osv_id: 'GHSA-27h2-hvpr-p74q',
    aliases: ['CVE-2022-23529'],
    purl: 'pkg:npm/jsonwebtoken@8.5.1',
    package_name: 'jsonwebtoken',
    installed_version: '8.5.1',
    fixed_version: '9.0.0',
    severity: 'critical',
    status: 'open',
    is_direct: true,
    first_seen_at: minutesAgo(12),
  },
  {
    id: 'v_lodash',
    repo_id: 'repo_test_app',
    osv_id: 'GHSA-29mw-wpgm-hmr9',
    aliases: ['CVE-2020-8203'],
    purl: 'pkg:npm/lodash@4.17.20',
    package_name: 'lodash',
    installed_version: '4.17.20',
    fixed_version: '4.17.21',
    severity: 'high',
    status: 'open',
    is_direct: true,
    first_seen_at: minutesAgo(12),
  },
  {
    id: 'v_qs',
    repo_id: 'repo_test_app',
    osv_id: 'GHSA-hrpp-h998-j3pp',
    aliases: ['CVE-2022-24999'],
    purl: 'pkg:npm/qs@6.5.2',
    package_name: 'qs',
    installed_version: '6.5.2',
    fixed_version: '6.5.3',
    severity: 'high',
    status: 'open',
    is_direct: false,
    first_seen_at: minutesAgo(12),
  },
  {
    id: 'v_minimist',
    repo_id: 'repo_test_app',
    osv_id: 'GHSA-xvch-5gv4-984h',
    aliases: ['CVE-2021-44906'],
    purl: 'pkg:npm/minimist@0.0.8',
    package_name: 'minimist',
    installed_version: '0.0.8',
    fixed_version: '1.2.6',
    severity: 'medium',
    status: 'open',
    is_direct: false,
    first_seen_at: minutesAgo(12),
  },
  {
    id: 'v_semver',
    repo_id: 'repo_test_app',
    osv_id: 'GHSA-c2qf-rxjj-qqgw',
    purl: 'pkg:npm/semver@5.7.1',
    package_name: 'semver',
    installed_version: '5.7.1',
    fixed_version: null,
    severity: 'medium',
    status: 'unfixable',
    is_direct: false,
    first_seen_at: minutesAgo(900),
  },
]

const EDGES: DependencyEdge[] = [
  {
    id: 'e1',
    repo_id: 'repo_test_app',
    parent_purl: 'ROOT',
    child_purl: 'pkg:npm/express@4.16.0',
    requested_range: '^4.16.0',
  },
  {
    id: 'e2',
    repo_id: 'repo_test_app',
    parent_purl: 'pkg:npm/express@4.16.0',
    child_purl: 'pkg:npm/qs@6.5.2',
    requested_range: '6.5.2',
  },
  {
    id: 'e3',
    repo_id: 'repo_test_app',
    parent_purl: 'ROOT',
    child_purl: 'pkg:npm/mkdirp@0.5.1',
    requested_range: '^0.5.1',
  },
  {
    id: 'e4',
    repo_id: 'repo_test_app',
    parent_purl: 'pkg:npm/mkdirp@0.5.1',
    child_purl: 'pkg:npm/minimist@0.0.8',
    requested_range: '0.0.8',
  },
  {
    id: 'e5',
    repo_id: 'repo_test_app',
    parent_purl: 'ROOT',
    child_purl: 'pkg:npm/jsonwebtoken@8.5.1',
    requested_range: '^8.5.1',
  },
  {
    id: 'e6',
    repo_id: 'repo_test_app',
    parent_purl: 'ROOT',
    child_purl: 'pkg:npm/lodash@4.17.20',
    requested_range: '^4.17.20',
  },
]

/** The run the demo plays out, one step at a time, when you press Fix now. */
const SCRIPT: ReadonlyArray<{
  after: number
  state: AgentRun['state']
  type: AgentEvent['type']
  message: string
  attempt?: number
  pr?: boolean
}> = [
  { after: 0, state: 'QUEUED', type: 'state_change', message: 'Run queued (manual)' },
  {
    after: 1200,
    state: 'PLANNING',
    type: 'state_change',
    message: 'Selected 4 vulnerabilities to fix',
  },
  {
    after: 2600,
    state: 'PATCHING',
    type: 'state_change',
    message:
      'Planned 4 changes: jsonwebtoken 8.5.1 to 9.0.0, lodash 4.17.20 to 4.17.21, express 4.16.0 to 4.17.1 for qs, override minimist 1.2.6',
  },
  {
    after: 4200,
    state: 'PR_OPEN',
    type: 'state_change',
    message: 'Committed package.json and package-lock.json to vulnagent/run-8f21',
  },
  {
    after: 5400,
    state: 'AWAITING_CI',
    type: 'pr_opened',
    message: 'Opened pull request #42',
    pr: true,
  },
  {
    after: 8200,
    state: 'REPAIRING',
    type: 'ci_failed',
    message: 'CI failed: TypeError: jwt.sign is not a function at src/auth.ts',
  },
  {
    after: 9400,
    state: 'REPAIRING',
    type: 'memory_hit',
    message: 'Found a past fix for a similar failure (similarity 0.93)',
  },
  {
    after: 11000,
    state: 'AWAITING_CI',
    type: 'patch_pushed',
    message:
      'jsonwebtoken 9 removed the callable default export; switched to a namespace import and passed an explicit algorithm',
    attempt: 1,
  },
  { after: 14500, state: 'READY_TO_MERGE', type: 'ci_passed', message: 'CI passed' },
  { after: 16000, state: 'MERGED', type: 'merged', message: 'Pull request #42 merged' },
  {
    after: 17200,
    state: 'COMPLETED',
    type: 'state_change',
    message: '4 vulnerabilities marked fixed',
  },
]

class MockBackend {
  private readonly listeners = new Set<Listener>()
  private repos = REPOS.map((repo) => ({ ...repo }))
  private vulnerabilities = VULNERABILITIES.map((vuln) => ({ ...vuln }))
  private runs: AgentRun[] = []
  private events: AgentEvent[] = []
  private timers: number[] = []

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Back to the starting state, for tests and for a reloaded demo. */
  reset(): void {
    for (const timer of this.timers) window.clearTimeout(timer)
    this.timers = []
    this.repos = REPOS.map((repo) => ({ ...repo }))
    this.vulnerabilities = VULNERABILITIES.map((vuln) => ({ ...vuln }))
    this.runs = []
    this.events = []
  }

  listRepos(): Repo[] {
    return this.repos.map((repo) => ({ ...repo }))
  }

  getRepo(id: string): Repo | null {
    return this.repos.find((repo) => repo.id === id) ?? null
  }

  listVulnerabilities(repoId: string): Vulnerability[] {
    return this.vulnerabilities.filter((vuln) => vuln.repo_id === repoId)
  }

  listEdges(repoId: string): DependencyEdge[] {
    return EDGES.filter((edge) => edge.repo_id === repoId)
  }

  listRuns(repoId: string): AgentRun[] {
    return this.runs.filter((run) => run.repo_id === repoId)
  }

  listEvents(runId: string): AgentEvent[] {
    return this.events.filter((event) => event.run_id === runId)
  }

  scan(repoId: string): void {
    this.patchRepo(repoId, { agent_state: 'scanning' })
    this.later(() => {
      this.patchRepo(repoId, { agent_state: 'idle', last_scan_at: new Date().toISOString() })
    }, 2200)
  }

  /** Plays the scripted run so the interface can be watched end to end. */
  fix(repoId: string): string {
    const existing = this.repos.find((repo) => repo.id === repoId)?.active_run_id
    if (existing) return existing

    const runId = `run_${Date.now()}`
    this.runs = [
      {
        id: runId,
        repo_id: repoId,
        trigger: 'manual',
        state: 'QUEUED',
        attempt: 0,
        max_attempts: 3,
        pr_number: null,
        pr_url: null,
        last_error: null,
        created_at: new Date().toISOString(),
        completed_at: null,
      },
      ...this.runs,
    ]
    this.patchRepo(repoId, { agent_state: 'working', active_run_id: runId })

    for (const beat of SCRIPT) {
      this.later(() => this.play(runId, repoId, beat), beat.after)
    }
    return runId
  }

  private play(runId: string, repoId: string, beat: (typeof SCRIPT)[number]): void {
    this.runs = this.runs.map((run) =>
      run.id === runId
        ? {
            ...run,
            state: beat.state,
            attempt: beat.attempt ?? run.attempt,
            pr_number: beat.pr ? 42 : run.pr_number,
            pr_url: beat.pr ? 'https://github.com/pranav/vulnagent-test-app/pull/42' : run.pr_url,
            completed_at: beat.state === 'COMPLETED' ? new Date().toISOString() : run.completed_at,
          }
        : run,
    )
    this.events = [
      ...this.events,
      {
        id: `event_${this.events.length + 1}`,
        run_id: runId,
        repo_id: repoId,
        type: beat.type,
        message: beat.message,
        created_at: new Date().toISOString(),
      },
    ]

    if (beat.state === 'COMPLETED') {
      this.vulnerabilities = this.vulnerabilities.map((vuln) =>
        vuln.repo_id === repoId && vuln.status === 'open'
          ? { ...vuln, status: 'fixed' as const }
          : vuln,
      )
      this.patchRepo(repoId, {
        agent_state: 'idle',
        active_run_id: null,
        open_critical: 0,
        open_high: 0,
        open_medium: 0,
        last_scan_at: new Date().toISOString(),
      })
    }
    this.announce()
  }

  private patchRepo(repoId: string, changes: Partial<Repo>): void {
    this.repos = this.repos.map((repo) => (repo.id === repoId ? { ...repo, ...changes } : repo))
    this.announce()
  }

  private later(action: () => void, delay: number): void {
    this.timers.push(window.setTimeout(action, delay))
  }

  private announce(): void {
    for (const listener of this.listeners) listener()
  }
}

export const mockBackend = new MockBackend()
