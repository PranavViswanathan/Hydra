import { Account, Client, Databases, Functions } from 'appwrite'

export const DATABASE_ID = 'vulnagent'

export const config = {
  endpoint: import.meta.env.VITE_APPWRITE_ENDPOINT ?? 'https://cloud.appwrite.io/v1',
  projectId: import.meta.env.VITE_APPWRITE_PROJECT_ID ?? '',
  apiFunctionId: import.meta.env.VITE_API_FUNCTION_ID ?? '',
  appSlug: import.meta.env.VITE_GITHUB_APP_SLUG ?? '',
}

/**
 * With no project configured the dashboard runs on demo data, so the whole
 * interface can be seen before Appwrite exists.
 */
export const isDemo = config.projectId === ''

export const client = new Client().setEndpoint(config.endpoint).setProject(config.projectId)

export const account = new Account(client)
export const databases = new Databases(client)
export const functions = new Functions(client)

export function installUrl(): string {
  return config.appSlug
    ? `https://github.com/apps/${config.appSlug}/installations/new`
    : 'https://github.com/settings/apps'
}
