import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { Card } from '../components/primitives'
import { api } from '../lib/api'

/**
 * Where the GitHub App's setup URL returns to. Links the installation to the
 * signed-in user, then sends them to the overview.
 */
export function Setup() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const installationId = Number(params.get('installation_id') ?? 0)
    if (!installationId) {
      setError('GitHub did not send an installation id.')
      return
    }

    void api
      .linkInstallation(installationId, params.get('code') ?? '')
      .then(() => navigate('/', { replace: true }))
      .catch(() => setError('Could not link that installation to your account.'))
  }, [params, navigate])

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="px-8 py-10 text-center">
        {error ? (
          <>
            <p className="text-sm text-critical">{error}</p>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="mt-4 text-sm text-accent hover:underline"
            >
              Back to repositories
            </button>
          </>
        ) : (
          <p className="text-sm text-ink-200">Linking your installation…</p>
        )}
      </Card>
    </div>
  )
}
