import { useCallback, useEffect, useRef, useState } from 'react'
import { AuthContext } from './auth-context.js'
import {
  apiRequest,
  clearAccessToken,
  getAccessToken,
  SESSION_EXPIRED_EVENT,
  storeAccessToken,
} from '../api/client.js'

let startupValidationPromise = null

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(() => Boolean(getAccessToken()))
  const [sessionError, setSessionError] = useState('')
  const sessionExpiredHandled = useRef(false)

  const expireSession = useCallback(() => {
    if (sessionExpiredHandled.current) return
    sessionExpiredHandled.current = true
    setUser(null)
    setSessionError('Your session has expired. Please sign in again.')
    setIsLoading(false)
  }, [])

  useEffect(() => {
    let isCurrent = true
    const handleSessionExpired = () => {
      if (isCurrent) expireSession()
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)

    if (!getAccessToken()) {
      return () => {
        isCurrent = false
        window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
      }
    }

    if (!startupValidationPromise) {
      startupValidationPromise = apiRequest('/api/auth/me', { authenticated: true })
        .finally(() => {
          startupValidationPromise = null
        })
    }

    startupValidationPromise
      .then((result) => {
        if (isCurrent && !sessionExpiredHandled.current) setUser(result.user)
      })
      .catch((error) => {
        if (!isCurrent) return
        if (error.status === 401) {
          expireSession()
        } else {
          setUser(null)
          setSessionError('We could not verify your saved session. Check your connection or sign in again.')
        }
      })
      .finally(() => {
        if (isCurrent && !sessionExpiredHandled.current) setIsLoading(false)
      })

    return () => {
      isCurrent = false
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
    }
  }, [expireSession])

  async function login(email, password) {
    setSessionError('')
    const result = await apiRequest('/api/auth/login', {
      method: 'POST',
      body: { email, password },
    })

    if (!result?.access_token) {
      throw new Error('The server did not return an access token. Please try again.')
    }

    storeAccessToken(result.access_token)
    let authenticatedUser = result.user
    if (!authenticatedUser) {
      const current = await apiRequest('/api/auth/me', { authenticated: true })
      authenticatedUser = current.user
    }
    sessionExpiredHandled.current = false
    setUser(authenticatedUser)
    return authenticatedUser
  }

  function logout() {
    // Client-side logout only: the backend does not provide token revocation.
    clearAccessToken()
    sessionExpiredHandled.current = true
    setUser(null)
    setSessionError('')
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, sessionError, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
