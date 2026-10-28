import { Button, ExposureStrip } from '../components/primitives'
import { api } from '../lib/api'

const CLEAR = { critical: 0, high: 0, medium: 0, low: 0, unknown: 0 }

export function Login() {
  return (
    <div className="flex min-h-screen items-center px-4 sm:px-6">
      <div className="mx-auto w-full max-w-[34rem]">
        <h1 className="text-[40px] leading-none font-bold tracking-[-0.02em] font-stretch-[125%]">
          VulnAgent
        </h1>
        <p className="mt-4 text-[18px] text-lichen">
          Finds vulnerable dependencies, opens the pull request that fixes them, and keeps
          working until CI is green.
        </p>
        <div className="mt-8">
          <ExposureStrip counts={CLEAR} label="Open" />
        </div>
        <div className="mt-8">
          <Button variant="primary" onClick={() => void api.signIn()}>
            Sign in with GitHub
          </Button>
        </div>
      </div>
    </div>
  )
}
