import { useState } from 'react'
import ChatInterface from './components/ChatInterface.jsx'
import AuditLog from './components/AuditLog.jsx'
import ApprovalInbox from './components/ApprovalInbox.jsx'
import LoginPage from './components/LoginPage.jsx'
import { getStoredUser, logout } from './api.js'

const ROLE_STYLES = {
  employee:   { label: 'Employee',   color: '#60a5fa', bg: '#1e3a5f', border: '#2d5086' },
  hr_staff:   { label: 'HR Staff',   color: '#34d399', bg: '#0d2d22', border: '#1a5c3a' },
  hr_manager: { label: 'HR Manager', color: '#c084fc', bg: '#2d1a4e', border: '#4a2878' },
  admin:      { label: 'Admin',      color: '#f97316', bg: '#2d1500', border: '#7c3900' },
}

function getInitials(name) {
  return (name || '').split(' ').map(n => n[0]).slice(0, 2).join('').toUpperCase()
}

const HR_ROLES = new Set(['hr_staff', 'hr_manager', 'admin'])

export default function App() {
  const [user, setUser] = useState(() => getStoredUser())
  const [resetKey, setResetKey] = useState(0)
  const [inboxVisible, setInboxVisible] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)

  function handleLogin(userData) {
    setUser(userData)
    setResetKey(k => k + 1)
  }

  function handleLogout() {
    logout()
    setUser(null)
    setResetKey(k => k + 1)
    setInboxVisible(false)
    setPendingCount(0)
  }

  if (!user) {
    return <LoginPage onLogin={handleLogin} />
  }

  const roleStyle = ROLE_STYLES[user.role] || ROLE_STYLES.employee

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden', background: '#0f1117' }}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header style={{
        height: 58,
        background: '#0a0c14',
        borderBottom: '1px solid #1a1d2e',
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        gap: '20px',
        flexShrink: 0,
        zIndex: 10,
      }}>

        {/* Left: branding */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: '16px', color: '#e8e8f0', letterSpacing: '-0.4px', whiteSpace: 'nowrap' }}>
            Fotopia
          </div>
          <div style={{ width: 1, height: 18, background: '#252b42', flexShrink: 0 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '13px', color: '#9ca3af', whiteSpace: 'nowrap' }}>HR Agent</span>
            <span style={{
              fontSize: '11px',
              background: '#0d2218',
              color: '#4ade80',
              padding: '2px 8px',
              borderRadius: '10px',
              border: '1px solid #1a5c36',
              whiteSpace: 'nowrap',
            }}>
              Online
            </span>
          </div>
        </div>

        {/* Center: role badge */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            background: '#13151f', border: '1px solid #1a1d2e',
            borderRadius: '10px', padding: '6px 16px',
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: roleStyle.color, flexShrink: 0,
            }} />
            <span style={{ fontSize: '13px', color: roleStyle.color, fontWeight: 600 }}>
              {roleStyle.label}
            </span>
          </div>
        </div>

        {/* Right: inbox toggle (HR only) + user avatar + logout */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
          {HR_ROLES.has(user.role) && (
            <button
              onClick={() => setInboxVisible(v => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 12px', borderRadius: 7,
                background: inboxVisible ? '#2a1800' : 'transparent',
                border: `1px solid ${inboxVisible ? '#92400e' : '#252b42'}`,
                color: inboxVisible ? '#fbbf24' : '#6b7280',
                fontSize: '12px', cursor: 'pointer', fontFamily: 'inherit',
                transition: 'all 0.15s',
              }}
            >
              Inbox
              {pendingCount > 0 && (
                <span style={{
                  minWidth: 16, height: 16, borderRadius: 8,
                  background: '#f59e0b', color: '#1a0e00',
                  fontSize: 10, fontWeight: 700,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  padding: '0 4px',
                }}>
                  {pendingCount}
                </span>
              )}
            </button>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: 34, height: 34,
              borderRadius: '50%',
              background: roleStyle.bg,
              border: `1.5px solid ${roleStyle.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '12px', fontWeight: 700, color: roleStyle.color,
              flexShrink: 0,
            }}>
              {getInitials(user.display_name)}
            </div>
            <div>
              <div style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8f0', lineHeight: '1.3', whiteSpace: 'nowrap' }}>
                {user.display_name}
              </div>
              <div style={{ fontSize: '11px', color: roleStyle.color, lineHeight: '1.3', whiteSpace: 'nowrap' }}>
                {roleStyle.label}
              </div>
            </div>
          </div>
          <button
            onClick={handleLogout}
            style={{
              padding: '5px 12px', borderRadius: 7,
              background: 'transparent', border: '1px solid #252b42',
              color: '#6b7280', fontSize: '12px', cursor: 'pointer',
              fontFamily: 'inherit', transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.target.style.borderColor = '#374151'; e.target.style.color = '#9ca3af' }}
            onMouseLeave={e => { e.target.style.borderColor = '#252b42'; e.target.style.color = '#6b7280' }}
          >
            Sign out
          </button>
        </div>

      </header>

      {/* ── Body: chat + inbox/audit log ───────────────────────────────── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Chat panel (~60%) */}
        <div style={{ flex: 3, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRight: '1px solid #1a1d2e' }}>
          <ChatInterface key={resetKey} demoRole={user.role} onInboxToggle={HR_ROLES.has(user.role) ? () => setInboxVisible(v => !v) : undefined} />
        </div>

        {/* Approval inbox (HR only, toggled) */}
        {HR_ROLES.has(user.role) && inboxVisible && (
          <div style={{ flex: 2, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 320 }}>
            <ApprovalInbox visible={inboxVisible} onCountChange={setPendingCount} />
          </div>
        )}

        {/* Audit log panel (~40%) — hidden when inbox is open */}
        {!inboxVisible && (
          <div style={{ flex: 2, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 320 }}>
            <AuditLog />
          </div>
        )}

      </div>
    </div>
  )
}
