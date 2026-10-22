import { Card, CardHeader, Empty, relativeTime, runLabel } from './primitives'
import { useEvents } from '../hooks/useData'
import { isTerminal, type AgentEvent, type AgentRun, type RunState } from '../lib/types'

/** The step indicator from §14.3: Planning → PR → CI → Repair → Merge. */
const STEPS: ReadonlyArray<{ label: string; states: RunState[] }> = [
  { label: 'Planning', states: ['QUEUED', 'PLANNING'] },
  { label: 'Pull request', states: ['PATCHING', 'PR_OPEN'] },
  { label: 'CI', states: ['AWAITING_CI'] },
  { label: 'Repair', states: ['REPAIRING'] },
  { label: 'Merge', states: ['READY_TO_MERGE', 'MERGED', 'COMPLETED'] },
]

const EVENT_STYLE: Record<AgentEvent['type'], { dot: string; text: string }> = {
  state_change: { dot: 'bg-ink-600', text: 'text-ink-200' },
  info: { dot: 'bg-ink-600', text: 'text-ink-200' },
  pr_opened: { dot: 'bg-accent', text: 'text-ink-50' },
  ci_failed: { dot: 'bg-critical', text: 'text-critical' },
  ci_passed: { dot: 'bg-good', text: 'text-good' },
  memory_hit: { dot: 'bg-medium', text: 'text-medium' },
  patch_pushed: { dot: 'bg-accent', text: 'text-ink-50' },
  gave_up: { dot: 'bg-critical', text: 'text-critical' },
  merged: { dot: 'bg-good', text: 'text-good' },
  error: { dot: 'bg-critical', text: 'text-critical' },
}

export function AgentPanel({ run }: { run: AgentRun | null }) {
  const { data: events = [] } = useEvents(run?.id ?? null)

  if (!run) {
    return (
      <Card>
        <CardHeader title="Agent" />
        <Empty
          title="Sleeping 😴"
          hint="The agent wakes on a schedule, on a push that changes dependencies, or when you press Fix now."
        />
      </Card>
    )
  }

  const reached = furthestStep(run.state)
  const finished = isTerminal(run.state)

  return (
    <Card>
      <CardHeader
        title="Agent"
        right={
          <div className="flex items-center gap-3 text-sm">
            {run.attempt > 0 && (
              <span className="text-ink-400">
                repair {run.attempt}/{run.max_attempts}
              </span>
            )}
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
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-1 px-5 py-4">
        {STEPS.map((step, index) => {
          const state =
            index < reached ? 'done' : index === reached && !finished ? 'active' : 'pending'
          return (
            <div key={step.label} className="flex items-center gap-1">
              {index > 0 && (
                <span
                  className={`h-px w-6 ${index <= reached ? 'bg-accent/50' : 'bg-ink-700'}`}
                  aria-hidden
                />
              )}
              <span
                className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                  state === 'active'
                    ? 'bg-accent/15 text-accent ring-1 ring-accent/40'
                    : state === 'done'
                      ? 'text-ink-200'
                      : 'text-ink-600'
                }`}
              >
                {step.label}
              </span>
            </div>
          )
        })}
        <span className="ml-auto text-sm text-ink-400">{runLabel(run.state)}</span>
      </div>

      {run.last_error && (
        <p className="border-t border-ink-800 px-5 py-3 font-mono text-[12px] text-critical">
          {run.last_error}
        </p>
      )}

      <div className="border-t border-ink-800">
        {events.length === 0 ? (
          <Empty title="Waiting for the first step…" />
        ) : (
          <ol className="divide-y divide-ink-800/60">
            {events.map((event) => {
              const style = EVENT_STYLE[event.type]
              return (
                <li
                  key={event.id}
                  className={`event-row flex gap-3 px-5 py-2.5 text-sm ${
                    event.type === 'memory_hit' ? 'bg-medium/5' : ''
                  }`}
                >
                  <span className={`mt-1.5 size-2 shrink-0 rounded-full ${style.dot}`} aria-hidden />
                  <span className={`flex-1 ${style.text}`}>{event.message}</span>
                  <span className="shrink-0 text-xs text-ink-600">
                    {relativeTime(event.created_at)}
                  </span>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </Card>
  )
}

function furthestStep(state: RunState): number {
  const index = STEPS.findIndex((step) => step.states.includes(state))
  if (index >= 0) return index
  // GAVE_UP, CANCELLED and ERRORED stop wherever they stopped.
  return state === 'NOTHING_TO_DO' ? 0 : STEPS.length - 1
}
