/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APPWRITE_ENDPOINT?: string
  readonly VITE_APPWRITE_PROJECT_ID?: string
  readonly VITE_API_FUNCTION_ID?: string
  readonly VITE_GITHUB_APP_SLUG?: string
  readonly VITE_DEMO_BADGE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
