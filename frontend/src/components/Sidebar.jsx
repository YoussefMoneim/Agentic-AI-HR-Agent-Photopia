import { useState } from 'react'

// Week-1 simplification, stated explicitly: Threads is a local list this
// component maintains itself — there's no thread-persistence backend yet.
// Clicking "+ New thread" is the only entry that does something real (it
// remounts ChatInterface via onNewThread, which also clears the persisted
// chat session); clicking an older thread row only highlights it, it
// doesn't restore that conversation's content. Agents is a single fixed
// entry for the same reason — no agent_configs table exists yet.
export default function Sidebar({ onNewThread }) {
  const [threads, setThreads] = useState([{ id: 1, label: 'New conversation' }])
  const [activeThreadId, setActiveThreadId] = useState(1)

  function handleNewThread() {
    const id = Date.now()
    setThreads(prev => [{ id, label: 'New conversation' }, ...prev])
    setActiveThreadId(id)
    onNewThread()
  }

  return (
    <div style={{
      width: 220, flexShrink: 0, background: '#0a0c14',
      borderRight: '1px solid #1a1d2e',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      <div style={{ padding: '14px 12px 8px' }}>
        <button
          onClick={handleNewThread}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
            width: '100%', padding: '9px 12px',
            background: '#13151f', border: '1px solid #252b42', borderRadius: '9px',
            color: '#e8e8f0', fontSize: '13px', fontWeight: 600,
            cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = '#4f5fa8' }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = '#252b42' }}
        >
          <PlusIcon /> New thread
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px' }}>
        <SectionLabel>Threads</SectionLabel>
        {threads.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveThreadId(t.id)}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '7px 10px', marginBottom: '2px', borderRadius: '7px',
              background: activeThreadId === t.id ? '#13151f' : 'transparent',
              border: 'none', color: activeThreadId === t.id ? '#e8e8f0' : '#6b7280',
              fontSize: '13px', cursor: 'pointer', fontFamily: 'inherit',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: '10px 12px 14px', borderTop: '1px solid #1a1d2e' }}>
        <SectionLabel>Agents</SectionLabel>
        <div style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '7px 10px', borderRadius: '7px', color: '#e8e8f0', fontSize: '13px',
        }}>
          <span style={{
            width: 20, height: 20, borderRadius: '50%', background: '#2d3561',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '11px', fontWeight: 700, color: '#a5b4fc', flexShrink: 0,
          }}>
            F
          </span>
          Fotopia HR Agent
        </div>
      </div>
    </div>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: '11px', fontWeight: 600, color: '#4b5563',
      textTransform: 'uppercase', letterSpacing: '0.05em',
      padding: '6px 10px 4px',
    }}>
      {children}
    </div>
  )
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}
