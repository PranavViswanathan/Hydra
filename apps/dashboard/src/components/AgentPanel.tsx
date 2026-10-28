import { Empty, Section, Sheet, relativeTime, runLabel } from './primitives'
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

const FAILED: ReadonlySet<RunState> = new Set(['GAVE_UP', 'ERRORED'])

/** The mark's shape says what kind of event it is, so colour is never alone. */
const EVENT_STYLE: Record<AgentEvent['type'], { mark: string; text: string }> = {
  state_change: { mark: 'size-1.5 rounded-full bg-faint', text: 'text-graphite' },
  info: { mark: 'size-1.5 rounded-full bg-faint', text: 'text-graphite' },
  pr_opened: { mark: 'size-2 rounded-full bg-verdigris', text: 'text-graphite' },
  ci_failed: { mark: 'size-2 bg-critical', text: 'text-critical' },
  ci_passed: { mark: 'size-2 rounded-full bg-verdigris', text: 'text-verdigris' },
  memory_hit: { mark: 'size-2 rotate-45 bg-medium', text: 'text-graphite font-semibold' },
  patch_pushed: { mark: 'size-2 rounded-full bg-verdigris', text: 'text-graphite' },
  gave_up: { mark: 'size-2 bg-critical', text: 'text-critical' },
  merged: { mark: 'size-2.5 rounded-full bg-verdigris', text: 'text-verdigris font-semibold' },
  error: { mark: 'size-2 bg-critical', text: 'text-critical' },
}

export function AgentPanel({ run }: { run: AgentRun | null }) {
  const { data: events = [] } = useEvents(run?.id ?? null)

  if (!run) {
    return (
      <Section title="Agent">
        <Sheet>
          <Empty
            title="Sleeping"
            hint="The agent wakes on a schedule, on a push that changes dependencies, or when you press Fix now."
          />
        </Sheet>
      </Section>
    )
  }

  const reached = furthestStep(run.state)
  const finished = isTerminal(run.state)
  const failed = FAILED.has(run.state)

  return (
    <Section
      title="Agent"
      right={
        <div className="flex items-baseline gap-4 text-[14px] text-lichen">
          <span className={failed ? 'text-critical' : 'text-graphite'}>{runLabel(run.state)}</span>
          {run.attempt > 0 && (
            <span>
              repair {run.attempt} of {run.max_attempts}
            </span>
          )}
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
        </div>
      }
    >
      <Sheet>
        <ol className="grid grid-cols-5 gap-1 px-5 pt-5 pb-4" aria-label="Run progress">
          {STEPS.map((step, index) => {
            const state =
              index < reached || (index === reached && finished && !failed)
                ? 'done'
                : index === reached && failed
                  ? 'failed'
                  : index === reached
                    ? 'active'
                    : 'pending'
            return (
              <li key={step.label} aria-current={state === 'active' ? 'step' : undefined}>
                <span
                  className={`block h-1.5 rounded-[1px] ${
                    state === 'done'
                      ? 'bg-verdigris'
                      : state === 'active'
                        ? 'step-active'
                        : state === 'failed'
                          ? 'bg-critical'
                          : 'bg-rule'
                  }`}
                  aria-hidden
                />
                <span
                  className={`mt-2 block truncate text-[13px] ${
                    state === 'pending' ? 'text-faint' : 'text-graphite'
                  } ${state === 'active' ? 'font-semibold' : ''}`}
                >
                  {step.label}
                </span>
              </li>
            )
          })}
        </ol>

        {run.last_error && (
          <p className="border-t border-rule px-5 py-3 font-mono text-[12px] text-critical">
            {run.last_error}
          </p>
        )}

        <div className="border-t border-rule">
          {events.length === 0 ? (
            <Empty title="Waiting for the first step…" />
          ) : (
            <ol className="relative py-2 before:absolute before:top-4 before:bottom-4 before:left-[27px] before:w-px before:bg-rule">
              {events.map((event) => {
                const style = EVENT_STYLE[event.type]
                return (
                  <li
                    key={event.id}
                    className={`event-row relative flex items-baseline gap-4 py-2 pr-5 pl-5 text-[14px] ${
                      event.type === 'memory_hit' ? 'bg-medium/12' : ''
                    }`}
                  >
                    <span className="flex w-4 shrink-0 justify-center self-center" aria-hidden>
                      <span className={`block ${style.mark}`} />
                    </span>
                    <span className={`flex-1 ${style.text}`}>{event.message}</span>
                    <span className="shrink-0 text-[13px] text-lichen tabular-nums">
                      {relativeTime(event.created_at)}
                    </span>
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      </Sheet>
    </Section>
  )
}

function furthestStep(state: RunState): number {
  const index = STEPS.findIndex((step) => step.states.includes(state))
  if (index >= 0) return index
  // GAVE_UP, CANCELLED and ERRORED stop wherever they stopped.
  return state === 'NOTHING_TO_DO' ? 0 : STEPS.length - 1
}
