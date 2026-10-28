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
    return <div className="p-10 text-[14px] text-lichen">Loading…</div>
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
      <main className="mx-auto max-w-[1120px] px-4 pt-10 pb-20 sm:px-6">
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
    <header className="sticky top-0 z-10 border-b border-rule bg-ground/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1120px] items-center justify-between px-4 py-3 sm:px-6">
        <a
          href="/"
          className="text-[17px] font-bold tracking-[-0.01em] font-stretch-[125%]"
        >
          VulnAgent
        </a>
        <div className="flex items-center gap-4">
          {api.demo && (
            <span
              className="rounded px-2 py-0.5 text-[12.5px] text-medium ring-1 ring-medium/50 ring-inset"
              title="No Appwrite project is configured, so this is demo data."
            >
              demo data
            </span>
          )}
          <span className="text-[14px] text-lichen">{name}</span>
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
