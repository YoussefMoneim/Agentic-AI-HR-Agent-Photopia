import { useState } from 'react'
import ChatInterface from './components/ChatInterface.jsx'
import AuditLog from './components/AuditLog.jsx'

const ROLES = {
  employee: {
    label: 'Employee',
    name: 'Saif Ahmed Hassan',
    initials: 'SA',
    color: '#60a5fa',
    bg: '#1e3a5f',
    border: '#2d5086',
  },
  hr_manager: {
    label: 'HR Manager',
    name: 'Nourhan Hosny',
    initials: 'NH',
    color: '#c084fc',
    bg: '#2d1a4e',
    border: '#4a2878',
  },
}

export default function App() {
  const [demoRole, setDemoRole] = useState('employee')
  const [resetKey, setResetKey] = useState(0)

  function switchRole(role) {
    if (role === demoRole) return
    setDemoRole(role)
    setResetKey(k => k + 1)
  }

  const role = ROLES[demoRole]

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

        {/* Center: role switcher */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <div style={{
            display: 'inline-flex',
            background: '#13151f',
            border: '1px solid #1a1d2e',
            borderRadius: '10px',
            padding: '4px',
            gap: '4px',
          }}>
            {Object.entries(ROLES).map(([key, r]) => {
              const active = demoRole === key
              return (
                <button
                  key={key}
                  onClick={() => switchRole(key)}
                  style={{
                    padding: '6px 20px',
                    borderRadius: '7px',
                    border: active ? `1px solid ${r.border}` : '1px solid transparent',
                    background: active ? r.bg : 'transparent',
                    color: active ? r.color : '#555',
                    fontSize: '13px',
                    fontWeight: active ? 600 : 400,
                    cursor: 'pointer',
                    transition: 'all 0.18s',
                    fontFamily: 'inherit',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {r.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Right: user avatar + name */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
          <div style={{
            width: 34, height: 34,
            borderRadius: '50%',
            background: role.bg,
            border: `1.5px solid ${role.border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '12px', fontWeight: 700, color: role.color,
            flexShrink: 0,
          }}>
            {role.initials}
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8f0', lineHeight: '1.3', whiteSpace: 'nowrap' }}>
              {role.name}
            </div>
            <div style={{ fontSize: '11px', color: role.color, lineHeight: '1.3', whiteSpace: 'nowrap' }}>
              {role.label}
            </div>
          </div>
        </div>

      </header>

      {/* ── Body: chat + audit log ──────────────────────────────────────── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Chat panel (~60%) */}
        <div style={{ flex: 3, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRight: '1px solid #1a1d2e' }}>
          <ChatInterface key={resetKey} demoRole={demoRole} />
        </div>

        {/* Audit log panel (~40%) */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 320 }}>
          <AuditLog />
        </div>

      </div>
    </div>
  )
}
