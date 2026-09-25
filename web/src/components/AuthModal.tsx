import { useState } from 'react'
import confetti from 'canvas-confetti'
import { LogIn, Shield, UserPlus, X } from 'lucide-react'
import { useAuth } from '../auth'
import { useToast } from '../toast'

interface AuthModalProps {
  isOpen: boolean
  onClose: () => void
  initialMode?: 'login' | 'signup'
  onSuccess?: () => void
}

export function AuthModal({ isOpen, onClose, initialMode = 'login', onSuccess }: AuthModalProps) {
  const { login, signup } = useAuth()
  const { show } = useToast()
  const [mode, setMode] = useState<'login' | 'signup'>(initialMode)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!isOpen) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      if (mode === 'login') {
        await login(username, password)
        show(`Welcome back, ${username}!`)
      } else {
        await signup(username, password, fullName)
        show(`Account created! Welcome to CallForge, ${username}!`)
      }

      // Celebratory confetti matching Sarvam AI palette
      try {
        confetti({
          particleCount: 60,
          spread: 60,
          origin: { y: 0.6 },
          colors: ['#10b981', '#6366f1', '#111827', '#ffffff'],
        })
      } catch {
        /* ignore */
      }

      onClose()
      onSuccess?.()
    } catch (err) {
      show((err as Error).message, true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(17, 24, 39, 0.45)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '440px',
          background: '#ffffff',
          border: '1px solid #e5e7eb',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.15)',
          position: 'relative',
          borderRadius: '24px',
          overflow: 'hidden',
        }}
      >
        {/* Top Header */}
        <div
          style={{
            padding: '1.25rem 1.5rem',
            background: '#fafafa',
            borderBottom: '1px solid #e5e7eb',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '8px',
                background: '#111827',
                color: '#ffffff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 800,
                fontSize: '0.85rem',
                letterSpacing: '-0.03em',
                boxShadow: '0 2px 6px rgba(0, 0, 0, 0.12)',
              }}
            >
              CF
            </div>
            <div>
              <div style={{ fontSize: '0.98rem', fontWeight: 700, color: '#111827', letterSpacing: '-0.02em' }}>
                CallForge Console
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b' }}>AI Telephony Fleet Access</div>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              color: '#64748b',
              borderRadius: '8px',
              cursor: 'pointer',
              padding: '0.35rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = '#111827'
              e.currentTarget.style.color = '#111827'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#e5e7eb'
              e.currentTarget.style.color = '#64748b'
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '1.75rem' }}>
          {/* Mode Switcher Pills */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              background: '#f1f5f9',
              padding: '4px',
              borderRadius: '12px',
              border: '1px solid #e2e8f0',
              marginBottom: '1.5rem',
            }}
          >
            <button
              type="button"
              onClick={() => setMode('login')}
              style={{
                padding: '0.6rem',
                borderRadius: '8px',
                border: 'none',
                background: mode === 'login' ? '#ffffff' : 'transparent',
                color: mode === 'login' ? '#111827' : '#64748b',
                fontWeight: mode === 'login' ? 700 : 500,
                fontSize: '0.84rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.4rem',
                transition: 'all 0.15s ease',
                boxShadow: mode === 'login' ? '0 1px 3px rgba(0, 0, 0, 0.08)' : 'none',
              }}
            >
              <LogIn size={15} />
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setMode('signup')}
              style={{
                padding: '0.6rem',
                borderRadius: '8px',
                border: 'none',
                background: mode === 'signup' ? '#ffffff' : 'transparent',
                color: mode === 'signup' ? '#111827' : '#64748b',
                fontWeight: mode === 'signup' ? 700 : 500,
                fontSize: '0.84rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.4rem',
                transition: 'all 0.15s ease',
                boxShadow: mode === 'signup' ? '0 1px 3px rgba(0, 0, 0, 0.08)' : 'none',
              }}
            >
              <UserPlus size={15} />
              Create Account
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.15rem' }}>
            {mode === 'signup' && (
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#374151', fontWeight: 600, marginBottom: '0.4rem' }}>
                  Full Name (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Himanshu Sharma"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.75rem 0.95rem',
                    background: '#ffffff',
                    border: '1px solid #d1d5db',
                    borderRadius: '10px',
                    color: '#111827',
                    fontSize: '0.9rem',
                    outline: 'none',
                    transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = '#111827'
                    e.currentTarget.style.boxShadow = '0 0 0 3px rgba(17, 24, 39, 0.08)'
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = '#d1d5db'
                    e.currentTarget.style.boxShadow = 'none'
                  }}
                />
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#374151', fontWeight: 600, marginBottom: '0.4rem' }}>
                Username *
              </label>
              <input
                type="text"
                required
                placeholder="e.g. himanshu"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem 0.95rem',
                  background: '#ffffff',
                  border: '1px solid #d1d5db',
                  borderRadius: '10px',
                  color: '#111827',
                  fontSize: '0.9rem',
                  outline: 'none',
                  transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = '#111827'
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(17, 24, 39, 0.08)'
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = '#d1d5db'
                  e.currentTarget.style.boxShadow = 'none'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#374151', fontWeight: 600, marginBottom: '0.4rem' }}>
                Password *
              </label>
              <input
                type="password"
                required
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem 0.95rem',
                  background: '#ffffff',
                  border: '1px solid #d1d5db',
                  borderRadius: '10px',
                  color: '#111827',
                  fontSize: '0.9rem',
                  outline: 'none',
                  transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = '#111827'
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(17, 24, 39, 0.08)'
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = '#d1d5db'
                  e.currentTarget.style.boxShadow = 'none'
                }}
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              style={{
                marginTop: '0.5rem',
                padding: '0.85rem',
                background: '#2a2c33',
                border: '1px solid rgba(0, 0, 0, 0.1)',
                borderRadius: '9999px',
                color: '#ffffff',
                fontWeight: 500,
                fontSize: '0.9rem',
                cursor: 'pointer',
                boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.4), inset 0 -2px 0 rgba(0, 0, 0, 0.2)',
                opacity: submitting ? 0.7 : 1,
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = '#1a1b20' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = '#2a2c33' }}
            >
              {submitting
                ? 'Authenticating...'
                : mode === 'login'
                  ? 'Sign In to Console'
                  : 'Create Operator Account'}
            </button>
          </form>

          {/* Security footnote */}
          <div
            style={{
              marginTop: '1.5rem',
              paddingTop: '1rem',
              borderTop: '1px solid #e5e7eb',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '0.75rem',
              color: '#64748b',
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <Shield size={13} style={{ color: '#10b981' }} /> SHA-256 Secured
            </span>
            <span>REST API :8080</span>
          </div>
        </div>
      </div>
    </div>
  )
}
