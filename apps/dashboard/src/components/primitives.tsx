import type { ReactNode } from 'react'

import type { AgentState, RunState, Severity } from '../lib/types'

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: 'bg-critical/15 text-critical ring-critical/30',
  high: 'bg-high/15 text-high ring-high/30',
  medium: 'bg-medium/15 text-medium ring-medium/30',
  low: 'bg-low/15 text-low ring-low/30',
  unknown: 'bg-unknown/15 text-unknown ring-unknown/30',
}

export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${SEVERITY_STYLE[severity]}`}
    >
      {count !== undefined && <span className="font-mono tabular-nums">{count}</span>}
      {severity}
    </span>
  )
}

export function SeverityDot({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-block size-2 rounded-full ${SEVERITY_STYLE[severity].split(' ')[0]?.replace('/15', '')}`}
      aria-hidden
    />
  )
}

const AGENT_LABEL: Record<AgentState, { text: string; className: string }> = {
  idle: { text: 'Sleeping 😴', className: 'text-ink-400' },
  scanning: { text: 'Scanning', className: 'text-accent' },
  working: { text: 'Working', className: 'text-accent' },
  error: { text: 'Needs attention', className: 'text-critical' },
}

export function AgentStateBadge({ state }: { state: AgentState }) {
  const label = AGENT_LABEL[state]
  const busy = state === 'working' || state === 'scanning'
  return (
    <span className={`inline-flex items-center gap-2 text-sm ${label.className}`}>
      <span
        className={`inline-block size-2 rounded-full ${busy ? 'bg-accent working-dot' : state === 'error' ? 'bg-critical' : 'bg-ink-600'}`}
        aria-hidden
      />
      {label.text}
    </span>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[13px]">{children}</span>
}

export function Button({
  children,
  onClick,
  variant = 'secondary',
  disabled,
  title,
}: {
  children: ReactNode
  onClick?: (() => void) | undefined
  variant?: 'primary' | 'secondary' | 'ghost' | undefined
  disabled?: boolean | undefined
  title?: string | undefined
}) {
  const styles = {
    primary: 'bg-accent text-ink-950 hover:bg-accent/85 font-medium',
    secondary: 'bg-ink-800 text-ink-100 hover:bg-ink-700 ring-1 ring-inset ring-ink-700',
    ghost: 'text-ink-400 hover:text-ink-50 hover:bg-ink-800',
  }[variant]

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-md px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-xl border border-ink-800 bg-ink-900/60 backdrop-blur-sm ${className}`}
    >
      {children}
    </section>
  )
}

export function CardHeader({ title, right }: { title: ReactNode; right?: ReactNode }) {
  return (
    <header className="flex items-center justify-between border-b border-ink-800 px-5 py-3.5">
      <h2 className="text-sm font-semibold tracking-wide text-ink-200 uppercase">{title}</h2>
      {right}
    </header>
  )
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="text-sm text-ink-200">{title}</p>
      {hint && <div className="mt-2 text-sm text-ink-400">{hint}</div>}
    </div>
  )
}

export function relativeTime(value: string | null): string {
  if (!value) return 'never'
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

const RUN_LABEL: Record<RunState, string> = {
  QUEUED: 'Queued',
  PLANNING: 'Planning',
  PATCHING: 'Patching',
  PR_OPEN: 'Opening PR',
  AWAITING_CI: 'Waiting for CI',
  REPAIRING: 'Repairing',
  READY_TO_MERGE: 'Ready to merge',
  MERGED: 'Merged',
  COMPLETED: 'Completed',
  GAVE_UP: 'Gave up',
  CANCELLED: 'Cancelled',
  ERRORED: 'Errored',
  NOTHING_TO_DO: 'Nothing to do',
}

export function runLabel(state: RunState): string {
  return RUN_LABEL[state]
}
