import { Button, Card } from '../components/primitives'
import { api } from '../lib/api'

export function Login() {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <Card className="w-full max-w-md px-8 py-10 text-center">
        <div className="text-4xl">🔒</div>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">VulnAgent</h1>
        <p className="mt-2 text-sm text-ink-400">
          An agent that finds vulnerable dependencies, opens the pull request that fixes them, and
          keeps working until CI is green.
        </p>
        <div className="mt-8">
          <Button variant="primary" onClick={() => void api.signIn()}>
            Sign in with GitHub
          </Button>
        </div>
      </Card>
    </div>
  )
}
