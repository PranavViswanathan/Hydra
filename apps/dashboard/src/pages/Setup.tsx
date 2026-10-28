import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { Sheet } from '../components/primitives'
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
      <Sheet className="px-8 py-10">
        {error ? (
          <>
            <p className="text-critical">{error}</p>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="mt-4 text-[14px] text-verdigris hover:underline"
            >
              Back to repositories
            </button>
          </>
        ) : (
          <p className="text-graphite">Linking your installation…</p>
        )}
      </Sheet>
    </div>
  )
}
