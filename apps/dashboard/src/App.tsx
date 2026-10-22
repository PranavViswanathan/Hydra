import { Navigate, Route, Routes } from 'react-router-dom'

import { Button } from './components/primitives'
import { useLiveUpdates, useSession } from './hooks/useData'
import { api } from './lib/api'
import { Login } from './pages/Login'
import { Overview } from './pages/Overview'
import { RepoDetail } from './pages/RepoDetail'
import { Setup } from './pages/Setup'

export function App() {
  const { data: session, isLoading } = useSession()
  useLiveUpdates()

  if (isLoading) {
    return <div className="p-10 text-sm text-ink-400">Loading…</div>
  }

  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  return (
    <div className="min-h-screen">
      <TopBar name={session.name} />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/repos/:repoId" element={<RepoDetail />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

function TopBar({ name }: { name: string }) {
  return (
    <header className="sticky top-0 z-10 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <a href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span aria-hidden>🔒</span> VulnAgent
        </a>
        <div className="flex items-center gap-3">
          {api.demo && (
            <span
              className="rounded-md bg-medium/15 px-2 py-0.5 text-xs text-medium ring-1 ring-medium/30 ring-inset"
              title="No Appwrite project is configured, so this is demo data."
            >
              demo data
            </span>
          )}
          <span className="text-sm text-ink-400">{name}</span>
          {!api.demo && (
            <Button
              variant="ghost"
              onClick={() => void api.signOut().then(() => window.location.reload())}
            >
              Sign out
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}
