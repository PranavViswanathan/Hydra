export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'unknown'

export const SEVERITIES: readonly Severity[] = ['critical', 'high', 'medium', 'low', 'unknown']

export type AgentState = 'idle' | 'scanning' | 'working' | 'error'

export type VulnStatus =
  | 'open'
  | 'in_progress'
  | 'fixed'
  | 'ignored'
  | 'unfixable'
  | 'needs_major'

export type RunState =
  | 'QUEUED'
  | 'PLANNING'
  | 'PATCHING'
  | 'PR_OPEN'
  | 'AWAITING_CI'
  | 'REPAIRING'
  | 'READY_TO_MERGE'
  | 'MERGED'
  | 'COMPLETED'
  | 'GAVE_UP'
  | 'CANCELLED'
  | 'ERRORED'
  | 'NOTHING_TO_DO'

export type EventType =
  | 'state_change'
  | 'info'
  | 'pr_opened'
  | 'ci_failed'
  | 'ci_passed'
  | 'memory_hit'
  | 'patch_pushed'
  | 'gave_up'
  | 'merged'
  | 'error'

export interface Repo {
  id: string
  full_name: string
  default_branch: string
  has_config: boolean
  config_error: string | null
  ecosystems: string[]
  agent_state: AgentState
  active_run_id: string | null
  last_scan_at: string | null
  open_critical: number
  open_high: number
  open_medium: number
  open_low: number
  open_unknown: number
}

export interface Vulnerability {
  id: string
  repo_id: string
  osv_id: string
  aliases?: string[]
  purl: string
  package_name: string
  installed_version: string
  fixed_version: string | null
  severity: Severity
  status: VulnStatus
  is_direct: boolean
  first_seen_at: string
}

export interface AgentRun {
  id: string
  repo_id: string
  trigger: 'auto' | 'manual'
  state: RunState
  attempt: number
  max_attempts: number
  pr_number: number | null
  pr_url: string | null
  last_error: string | null
  created_at: string
  completed_at: string | null
}

export interface AgentEvent {
  id: string
  run_id: string
  repo_id: string
  type: EventType
  message: string
  created_at: string
}

export interface DependencyEdge {
  id: string
  repo_id: string
  parent_purl: string
  child_purl: string
  requested_range: string
}

export function openCount(repo: Repo): number {
  return (
    repo.open_critical + repo.open_high + repo.open_medium + repo.open_low + repo.open_unknown
  )
}

export function countsOf(repo: Repo): Record<Severity, number> {
  return {
    critical: repo.open_critical,
    high: repo.open_high,
    medium: repo.open_medium,
    low: repo.open_low,
    unknown: repo.open_unknown,
  }
}

const TERMINAL: ReadonlySet<RunState> = new Set([
  'COMPLETED',
  'GAVE_UP',
  'CANCELLED',
  'ERRORED',
  'NOTHING_TO_DO',
])

export function isTerminal(state: RunState): boolean {
  return TERMINAL.has(state)
}
