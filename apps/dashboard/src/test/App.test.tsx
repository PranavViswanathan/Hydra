/**
 * The dashboard against its demo data, which is the same path a real project
 * takes: every page reads through `api`, so proving the flow here proves the
 * wiring, not the data source.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../App'

function show(route = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function rowFor(name: string): Promise<HTMLElement> {
  const link = await screen.findByRole('link', { name })
  const row = link.closest('tr')
  if (!row) throw new Error(`no table row for ${name}`)
  return row
}

describe('the repositories overview', () => {
  it('lists the repositories that are configured', async () => {
    show()

    expect(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'pranav/checkout-api' })).toBeVisible()
  })

  it('totals the open vulnerabilities by severity', async () => {
    show()

    await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' })
    const critical = screen.getByText('critical', { selector: 'p' }).previousElementSibling

    expect(critical).toHaveTextContent('1')
  })

  it('states how many vulnerabilities are open and where', async () => {
    show()

    expect(
      await screen.findByRole('heading', {
        name: '13 open vulnerabilities across 4 repositories',
      }),
    ).toBeVisible()
  })

  it('says the agent is asleep when no repository is being worked on', async () => {
    show()

    expect(await screen.findByText('The agent is asleep.')).toBeVisible()
  })

  it('names the repository the agent is working on', async () => {
    show()
    const row = await rowFor('pranav/vulnagent-test-app')

    await userEvent.click(within(row).getByRole('button', { name: 'Fix now' }))

    expect(
      await screen.findByText('The agent is working on pranav/vulnagent-test-app.'),
    ).toBeVisible()
  })

  it('reads the exposure strip out by severity', async () => {
    show()

    expect(
      await screen.findByRole('img', {
        name: 'Open across all repositories: 1 critical, 3 high, 3 medium, 3 low, 3 unknown',
      }),
    ).toBeInTheDocument()
  })

  it('shows the severity breakdown on each repository', async () => {
    show()

    const row = await rowFor('pranav/vulnagent-test-app')

    expect(within(row).getByText('critical')).toBeVisible()
    expect(within(row).getByText('high')).toBeVisible()
  })

  it('says a repository is sleeping when the agent is idle', async () => {
    show()

    const row = await rowFor('pranav/vulnagent-test-app')

    expect(within(row).getByText(/Sleeping/)).toBeVisible()
  })

  it('separates repositories that have no config yet', async () => {
    show()

    expect(await screen.findByText('Not configured')).toBeVisible()
    expect(screen.getByText('pranav/docs-site')).toBeVisible()
  })

  it('offers the sample config for an unconfigured repository', async () => {
    show()

    expect(await screen.findByRole('button', { name: 'Copy sample config' })).toBeVisible()
  })

  it('brands the top bar as Hydra, linking home', async () => {
    show()

    expect(await screen.findByRole('link', { name: 'Hydra' })).toHaveAttribute('href', '/')
  })

  it('marks the session as demo data when no project is configured', async () => {
    show()

    expect(await screen.findByText('demo data')).toBeVisible()
  })
})

describe('a repository in detail', () => {
  it('lists the vulnerabilities with their advisories', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))

    expect(await screen.findByRole('link', { name: 'GHSA-27h2-hvpr-p74q' })).toBeVisible()
  })

  it('shows what each package would be upgraded to', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))

    const row = (await screen.findByText('jsonwebtoken')).closest('tr')

    expect(within(row as HTMLElement).getByText('8.5.1')).toBeVisible()
    expect(within(row as HTMLElement).getByText('9.0.0')).toBeVisible()
  })

  it('explains why a transitive package is installed', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))

    const qs = (await screen.findByRole('link', { name: 'GHSA-hrpp-h998-j3pp' })).closest('tr')
    await userEvent.click(within(qs as HTMLElement).getByRole('button', { name: 'transitive' }))

    expect(await screen.findByText('your package.json')).toBeVisible()
    expect(screen.getByText('express@4.16.0')).toBeVisible()
  })

  it('says an advisory with no fix cannot be fixed', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))
    await userEvent.click(screen.getByRole('button', { name: 'all' }))

    expect(await screen.findByText('no fix available')).toBeVisible()
  })

  it('shows the agent asleep before any run', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))

    expect(await screen.findByText(/wakes on a schedule/)).toBeVisible()
  })
})

describe('pressing Fix now', () => {
  it('starts a run and shows it on the timeline', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))
    await userEvent.click(screen.getByRole('button', { name: 'Fix now' }))

    expect(await screen.findByText('Run queued (manual)')).toBeVisible()
  })

  it('moves the repository out of the sleeping state', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))
    await userEvent.click(screen.getByRole('button', { name: 'Fix now' }))

    await waitFor(() => expect(screen.getByText('Working')).toBeVisible())
  })

  it('disables Fix now while the agent is already working', async () => {
    show()
    await userEvent.click(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' }))
    await userEvent.click(screen.getByRole('button', { name: 'Fix now' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Fix now' })).toBeDisabled())
  })

  it('works the same way from the overview', async () => {
    show()
    const row = await rowFor('pranav/vulnagent-test-app')

    await userEvent.click(within(row).getByRole('button', { name: 'Fix now' }))

    await waitFor(() => expect(within(row).getByText('Working')).toBeVisible())
  })
})

describe('presenting the demo', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('can hide the demo data badge while still showing the demo data', async () => {
    vi.stubEnv('VITE_DEMO_BADGE', 'off')
    vi.resetModules()
    const { App: PresentedApp } = await import('../App')
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 0 } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <PresentedApp />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('link', { name: 'pranav/vulnagent-test-app' })).toBeVisible()
    expect(screen.queryByText('demo data')).not.toBeInTheDocument()
  })
})
