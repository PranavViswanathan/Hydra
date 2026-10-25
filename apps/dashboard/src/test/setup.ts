import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import { mockBackend } from '../lib/mock'

// `globals: false` means Testing Library does not register its own cleanup,
// so without this every render stacks up in the same document and queries
// start matching elements left behind by earlier tests.
afterEach(() => {
  cleanup()
  // The demo backend is a module singleton; a run started by one test would
  // otherwise leave the repository "working" for the next one.
  mockBackend.reset()
})
