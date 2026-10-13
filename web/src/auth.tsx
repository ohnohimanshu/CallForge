import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export interface User {
  id: string
  username: string
  full_name: string
  created_at: string
}

interface AuthContextType {
  user: User | null
  token: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  signup: (username: string, password: string, fullName?: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => {
    try {
      const saved = localStorage.getItem('cf_user')
      return saved ? JSON.parse(saved) : null
    } catch {
      return null
    }
  })

  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem('cf_token') || null
  })

  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (token) {
      localStorage.setItem('cf_token', token)
    } else {
      localStorage.removeItem('cf_token')
    }
  }, [token])

  useEffect(() => {
    if (user) {
      localStorage.setItem('cf_user', JSON.stringify(user))
    } else {
      localStorage.removeItem('cf_user')
    }
  }, [user])

  async function login(username: string, password: string) {
    setLoading(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Login failed')
      }
      const data = await res.json()
      setUser(data.user)
      setToken(data.token)
    } finally {
      setLoading(false)
    }
  }

  async function signup(username: string, password: string, fullName: string = '') {
    setLoading(true)
    try {
      const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, full_name: fullName }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Signup failed')
      }
      const data = await res.json()
      setUser(data.user)
      setToken(data.token)
    } finally {
      setLoading(false)
    }
  }

  function logout() {
    setUser(null)
    setToken(null)
    localStorage.removeItem('cf_token')
    localStorage.removeItem('cf_user')
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
