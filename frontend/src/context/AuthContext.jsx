import { useEffect, useState } from 'react'
import { fetchCurrentUser } from '../api/client'
import { AuthContext } from './auth-context-def'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const savedToken = localStorage.getItem('legal_auth_token')
    const savedExpiresAt = localStorage.getItem('legal_auth_expires_at')
    const savedUserJson = localStorage.getItem('legal_auth_user')

    if (savedToken && savedExpiresAt) {
      const now = Date.now()
      if (now > Number(savedExpiresAt)) {
        // Expired after 1 day (24 hours)
        logout()
        setIsLoading(false)
        return
      }

      setToken(savedToken)
      if (savedUserJson) {
        try {
          setUser(JSON.parse(savedUserJson))
        } catch {
          // ignore parsing error
        }
      }

      // Verify token with backend
      fetchCurrentUser()
        .then((fetchedUser) => {
          if (fetchedUser) {
            setUser(fetchedUser)
            localStorage.setItem('legal_auth_user', JSON.stringify(fetchedUser))
          }
        })
        .catch(() => {
          logout()
        })
        .finally(() => {
          setIsLoading(false)
        })
    } else {
      setIsLoading(false)
    }
  }, [])

  function login(newToken, newUser, expiresInSeconds = 86400) {
    const expiresAt = Date.now() + expiresInSeconds * 1000
    setToken(newToken)
    setUser(newUser)
    localStorage.setItem('legal_auth_token', newToken)
    localStorage.setItem('legal_auth_user', JSON.stringify(newUser))
    localStorage.setItem('legal_auth_expires_at', String(expiresAt))
  }

  function logout() {
    setToken(null)
    setUser(null)
    localStorage.removeItem('legal_auth_token')
    localStorage.removeItem('legal_auth_user')
    localStorage.removeItem('legal_auth_expires_at')
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoggedIn: !!user,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
