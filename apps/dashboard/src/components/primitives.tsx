import type { ReactNode } from 'react'

import { SEVERITIES, type AgentState, type RunState, type Severity } from '../lib/types'

export const SEVERITY_BG: Record<Severity, string> = {
  critical: 'bg-critical',
  high: 'bg-high',
  medium: 'bg-medium',
  low: 'bg-low',
  unknown: 'bg-unknown',
}

const SEVERITY_TEXT: Record<Severity, string> = {
  critical: 'text-critical',
  high: 'text-high',
  medium: 'text-medium',
  low: 'text-low',
  unknown: 'text-unknown',
}

export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span className={`inline-flex items-baseline gap-1 text-[13px] ${SEVERITY_TEXT[severity]}`}>
      {count !== undefined && <span className="font-semibold tabular-nums">{count}</span>}
      {severity}
    </span>
  )
}

/**
 * Open vulnerabilities as one proportional bar. Segments keep their place when
 * a count reaches zero, so a merge drains the bar instead of redrawing it.
 */
export function ExposureStrip({
  counts,
  label,
  size = 'large',
}: {
  counts: Record<Severity, number>
  label: string
  size?: 'large' | 'small'
}) {
  const present = SEVERITIES.filter((severity) => counts[severity] > 0)
  const spoken =
    present.length === 0
      ? `${label}: none`
      : `${label}: ${present.map((severity) => `${counts[severity]} ${severity}`).join(', ')}`

  return (
    <div
      role="img"
      aria-label={spoken}
      className={`flex overflow-hidden rounded-[2px] ${size === 'large' ? 'h-3' : 'h-1.5'} ${
        present.length === 0 ? 'bg-verdigris/35' : 'bg-rule'
      }`}
    >
      {SEVERITIES.map((severity) => (
        <span
          key={severity}
          className={`strip-segment basis-0 ${SEVERITY_BG[severity]}`}
          style={{
            flexGrow: counts[severity],
            marginRight: counts[severity] > 0 && severity !== present.at(-1) ? 2 : 0,
          }}
        />
      ))}
    </div>
  )
}

export function StripLegend({ counts }: { counts: Record<Severity, number> }) {
  return (
    <div className="mt-3 flex flex-wrap gap-x-7 gap-y-2">
      {SEVERITIES.map((severity) => (
        <div key={severity} className="flex items-baseline gap-1.5">
          <span className={`size-2 shrink-0 self-center rounded-[1px] ${SEVERITY_BG[severity]}`} />
          <p
            className={`font-semibold tabular-nums ${counts[severity] === 0 ? 'text-faint' : 'text-graphite'}`}
          >
            {counts[severity]}
          </p>
          <p className="text-[14px] text-lichen">{severity}</p>
        </div>
      ))}
    </div>
  )
}

const AGENT_LABEL: Record<AgentState, { text: string; className: string; dot: string }> = {
  idle: { text: 'Sleeping', className: 'text-lichen', dot: 'bg-faint' },
  scanning: { text: 'Scanning', className: 'text-verdigris', dot: 'bg-verdigris' },
  working: { text: 'Working', className: 'text-verdigris', dot: 'bg-verdigris' },
  error: { text: 'Needs attention', className: 'text-critical', dot: 'bg-critical' },
}

export function AgentStateBadge({ state }: { state: AgentState }) {
  const label = AGENT_LABEL[state]
  return (
    <span className={`inline-flex items-center gap-2 text-[14px] ${label.className}`}>
      <span className={`inline-block size-1.5 rounded-full ${label.dot}`} aria-hidden />
      {label.text}
    </span>
  )
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12.5px] font-stretch-[87.5%]">{children}</span>
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
    primary: 'bg-verdigris text-on-verdigris hover:bg-verdigris/85 font-semibold',
    secondary: 'bg-sheet text-graphite ring-1 ring-inset ring-rule hover:ring-lichen',
    ghost: 'text-lichen hover:text-graphite',
  }[variant]

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded px-3 py-1.5 text-[14px] whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  )
}

export function Section({
  title,
  right,
  children,
}: {
  title: ReactNode
  right?: ReactNode
  children: ReactNode
}) {
  return (
    <section>
      <header className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-[18px] leading-tight font-semibold font-stretch-[112.5%]">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  )
}

export function Sheet({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`relative overflow-x-auto rounded-md bg-sheet ring-1 ring-rule ${className}`}>
      {children}
    </div>
  )
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="px-5 py-10">
      <p className="text-graphite">{title}</p>
      {hint && <div className="mt-1 max-w-[60ch] text-[14px] text-lichen">{hint}</div>}
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
