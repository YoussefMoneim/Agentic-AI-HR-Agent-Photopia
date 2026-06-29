import { useState } from 'react'
import { login } from '../api.js'

const DEMO_ACCOUNTS = [
  { email: 'noura.rashidi@fotopiatech.com', label: 'Noura Al Rashidi', role: 'HR Director',        color: '#c084fc', bg: '#2d1a4e', border: '#4a2878', initials: 'NR' },
  { email: 'saif.ahmed@fotopiatech.com',    label: 'Saif Ahmed',       role: 'Mobile Engineer',    color: '#60a5fa', bg: '#1e3a5f', border: '#2d5086', initials: 'SA' },
  { email: 'layla.qassimi@fotopiatech.com', label: 'Layla Al Qassimi', role: 'Data Analyst',       color: '#60a5fa', bg: '#1e3a5f', border: '#2d5086', initials: 'LQ' },
]

export default function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim() || !password.trim()) return
    setLoading(true)
    setError('')
    try {
      const user = await login(email.trim().toLowerCase(), password)
      onLogin(user)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  async function quickLogin(accountEmail) {
    setLoading(true)
    setError('')
    try {
      const user = await login(accountEmail, 'demo123')
      onLogin(user)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', width: '100vw', background: '#0f1117',
    }}>
      <div style={{
        width: 420, background: '#0a0c14',
        border: '1px solid #1a1d2e', borderRadius: 16,
        padding: '40px 36px', boxShadow: '0 24px 48px rgba(0,0,0,0.5)',
      }}>
        {/* Branding */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#e8e8f0', letterSpacing: '-0.5px' }}>
            Fotopia
          </div>
          <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>HR Agent Platform</div>
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 12, color: '#9ca3af', marginBottom: 6, fontWeight: 500 }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@fotopia.ai"
              autoComplete="email"
              style={{
                width: '100%', padding: '10px 12px', boxSizing: 'border-box',
                background: '#13151f', border: '1px solid #1a1d2e', borderRadius: 8,
                color: '#e8e8f0', fontSize: 14, outline: 'none', fontFamily: 'inherit',
              }}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 12, color: '#9ca3af', marginBottom: 6, fontWeight: 500 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              style={{
                width: '100%', padding: '10px 12px', boxSizing: 'border-box',
                background: '#13151f', border: '1px solid #1a1d2e', borderRadius: 8,
                color: '#e8e8f0', fontSize: 14, outline: 'none', fontFamily: 'inherit',
              }}
            />
          </div>

          {error && (
            <div style={{
              background: '#2d0f0f', border: '1px solid #7f1d1d', borderRadius: 8,
              padding: '10px 12px', marginBottom: 16, fontSize: 13, color: '#fca5a5',
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !email || !password}
            style={{
              width: '100%', padding: '11px', borderRadius: 8,
              background: loading ? '#1a1d2e' : '#4f46e5',
              border: 'none', color: '#e8e8f0', fontSize: 14, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
              opacity: (!email || !password) ? 0.5 : 1,
            }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {/* Demo quick-login */}
        <div style={{ marginTop: 28 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
          }}>
            <div style={{ flex: 1, height: 1, background: '#1a1d2e' }} />
            <span style={{ fontSize: 11, color: '#4b5563', whiteSpace: 'nowrap' }}>Demo accounts</span>
            <div style={{ flex: 1, height: 1, background: '#1a1d2e' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {DEMO_ACCOUNTS.map(acc => (
              <button
                key={acc.email}
                onClick={() => quickLogin(acc.email)}
                disabled={loading}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 14px', borderRadius: 9,
                  background: acc.bg, border: `1px solid ${acc.border}`,
                  cursor: loading ? 'not-allowed' : 'pointer', textAlign: 'left',
                  fontFamily: 'inherit', opacity: loading ? 0.6 : 1,
                  transition: 'opacity 0.15s',
                }}
              >
                <div style={{
                  width: 32, height: 32, borderRadius: '50%',
                  background: 'rgba(0,0,0,0.3)', border: `1.5px solid ${acc.border}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700, color: acc.color, flexShrink: 0,
                }}>
                  {acc.initials}
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: acc.color, lineHeight: 1.3 }}>
                    {acc.label}
                  </div>
                  <div style={{ fontSize: 11, color: '#6b7280', lineHeight: 1.3 }}>
                    {acc.role} · demo123
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
