const TOKEN_STORAGE_KEY = 'nyumbaflow.access_token'
export const SESSION_EXPIRED_EVENT = 'nyumbaflow:session-expired'

export function getAccessToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function storeAccessToken(token) {
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    throw new Error('Your browser could not save this session. Enable session storage and try again.')
  }
}

export function clearAccessToken() {
  try {
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    // Clearing is best-effort when browser storage is unavailable.
  }
}

export class ApiError extends Error {
  constructor(message, status, body = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function readResponse(response) {
  const text = await response.text()
  if (!text) return null

  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function apiRequest(path, {
  method = 'GET',
  body,
  authenticated = false,
  headers = {},
} = {}) {
  const requestHeaders = new Headers(headers)
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json')

  if (authenticated) {
    const token = getAccessToken()
    if (token) requestHeaders.set('Authorization', `Bearer ${token}`)
  }

  let response
  try {
    response = await fetch(path, {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Unable to reach NyumbaFlow. Check your connection and try again.')
  }

  const result = await readResponse(response)
  if (response.status === 401 && authenticated) {
    clearAccessToken()
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  }
  if (!response.ok) {
    const message = result && typeof result === 'object'
      ? result.error || result.message
      : null
    throw new ApiError(
      typeof message === 'string' ? message : `Request failed (${response.status}).`,
      response.status,
      result,
    )
  }

  return result
}
