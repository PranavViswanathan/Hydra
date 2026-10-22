/**
 * One data source for the whole dashboard.
 *
 * Against a configured project it reads TablesDB through the Web SDK and
 * writes through the `api` function; with no project it answers from the demo
 * backend instead. Every page uses this, so nothing above here knows which.
 */

import { ExecutionMethod, Query } from 'appwrite'

import { DATABASE_ID, account, client, config, databases, functions, isDemo } from './appwrite'
import { mockBackend } from './mock'
import type { AgentEvent, AgentRun, DependencyEdge, Repo, Vulnerability } from './types'

const PAGE = 100

export interface Session {
  id: string
  name: string
  email: string
}

async function rows<T>(table: string, queries: string[]): Promise<T[]> {
  const response = await databases.listDocuments(DATABASE_ID, table, [
    ...queries,
    Query.limit(PAGE),
  ])
  return response.documents as unknown as T[]
}

async function callApi(path: string, body: Record<string, unknown> = {}): Promise<unknown> {
  const jwt = await account.createJWT()
  client.setJWT(jwt.jwt)
  const execution = await functions.createExecution(
    config.apiFunctionId,
    JSON.stringify(body),
    false,
    path,
    ExecutionMethod.POST,
  )
  return execution.responseBody ? JSON.parse(execution.responseBody) : {}
}

export const api = {
  demo: isDemo,

  async session(): Promise<Session | null> {
    if (isDemo) return { id: 'demo', name: 'Demo user', email: 'demo@vulnagent.local' }
    try {
      const me = await account.get()
      return { id: me.$id, name: me.name, email: me.email }
    } catch {
      return null
    }
  },

  async signIn(): Promise<void> {
    if (isDemo) return
    const origin = window.location.origin
    account.createOAuth2Session('github' as never, `${origin}/`, `${origin}/login?error=1`)
  },

  async signOut(): Promise<void> {
    if (isDemo) return
    await account.deleteSession('current')
  },

  async repos(): Promise<Repo[]> {
    if (isDemo) return mockBackend.listRepos()
    return rows<Repo>('repos', [Query.orderDesc('open_critical')])
  },

  async repo(id: string): Promise<Repo | null> {
    if (isDemo) return mockBackend.getRepo(id)
    try {
      return (await databases.getDocument(DATABASE_ID, 'repos', id)) as unknown as Repo
    } catch {
      return null
    }
  },

  async vulnerabilities(repoId: string): Promise<Vulnerability[]> {
    if (isDemo) return mockBackend.listVulnerabilities(repoId)
    return rows<Vulnerability>('vulnerabilities', [Query.equal('repo_id', repoId)])
  },

  async edges(repoId: string): Promise<DependencyEdge[]> {
    if (isDemo) return mockBackend.listEdges(repoId)
    return rows<DependencyEdge>('dependency_edges', [Query.equal('repo_id', repoId)])
  },

  async runs(repoId: string): Promise<AgentRun[]> {
    if (isDemo) return mockBackend.listRuns(repoId)
    return rows<AgentRun>('agent_runs', [
      Query.equal('repo_id', repoId),
      Query.orderDesc('created_at'),
    ])
  },

  async events(runId: string): Promise<AgentEvent[]> {
    if (isDemo) return mockBackend.listEvents(runId)
    return rows<AgentEvent>('agent_events', [
      Query.equal('run_id', runId),
      Query.orderAsc('created_at'),
    ])
  },

  async scanNow(repoId: string): Promise<void> {
    if (isDemo) {
      mockBackend.scan(repoId)
      return
    }
    await callApi(`/repos/${repoId}/scan`)
  },

  async fixNow(repoId: string): Promise<void> {
    if (isDemo) {
      mockBackend.fix(repoId)
      return
    }
    await callApi(`/repos/${repoId}/fix`)
  },

  async linkInstallation(installationId: number, githubToken: string): Promise<void> {
    if (isDemo) return
    await callApi('/link-installation', {
      installation_id: installationId,
      github_token: githubToken,
    })
  },

  /** Push changes: Appwrite Realtime, or the demo backend's own ticker. */
  watch(onChange: () => void): () => void {
    if (isDemo) return mockBackend.subscribe(onChange)

    return client.subscribe(
      [
        `databases.${DATABASE_ID}.tables.repos.rows`,
        `databases.${DATABASE_ID}.tables.vulnerabilities.rows`,
        `databases.${DATABASE_ID}.tables.agent_events.rows`,
        `databases.${DATABASE_ID}.tables.agent_runs.rows`,
      ],
      () => onChange(),
    )
  },
}
