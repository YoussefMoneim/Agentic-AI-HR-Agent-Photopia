import { useEffect, useRef, useState } from 'react'
import { fetchPendingCount, sendChat } from '../api.js'
import MessageBubble from './MessageBubble.jsx'

const QUICK_ACTIONS = {
  employee: [
    'Check my leave balance',
    'Request 3 days annual leave July 1-3',
    'Show my leave requests',
    "What is Saif Ahmed's employee profile?",
    'Generate a salary certificate for Saif Ahmed',
  ],
  hr_manager: [
    'Show pending approvals',
    "What is Saif Ahmed's employee profile?",
    'List all employees',
    'Generate a salary certificate for Saif Ahmed',
  ],
}

const WELCOME = {
  employee:
    "Hello Saif! I can check your leave balance, submit leave requests, and generate official documents. What would you like to do?",
  hr_manager:
    "Hello Nourhan! I can show pending approvals, look up employee data, and generate official HR documents. What would you like to do?",
}

export default function ChatInterface({ demoRole, onInboxToggle }) {
  const welcome = WELCOME[demoRole] || WELCOME.hr_manager
  const [messages, setMessages] = useState([
    { id: 0, role: 'agent', text: welcome, documents: [] },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [pendingCount, setPendingCount] = useState(0)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!onInboxToggle) return  // only poll for HR roles that have the inbox
    async function pollPending() {
      try {
        const data = await fetchPendingCount()
        setPendingCount(data.count || 0)
      } catch { /* keep showing last count */ }
    }
    pollPending()
    const id = setInterval(pollPending, 10000)
    return () => clearInterval(id)
  }, [demoRole, onInboxToggle])

  async function handleSend(text) {
    const msg = (text ?? input).trim()
    if (!msg || loading) return
    setInput('')

    setMessages(prev => [...prev, { id: Date.now(), role: 'user', text: msg, documents: [] }])
    setLoading(true)

    try {
      const data = await sendChat(msg, sessionId, demoRole)
      if (data.session_id && !sessionId) setSessionId(data.session_id)
      setMessages(prev => [
        ...prev,
        { id: Date.now() + 1, role: 'agent', text: data.response, documents: data.documents || [] },
      ])
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { id: Date.now() + 1, role: 'agent', text: `Something went wrong: ${err.message}`, documents: [] },
      ])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const displayName = demoRole === 'employee' ? 'Saif' : 'Nourhan'
  const actions = QUICK_ACTIONS[demoRole] || QUICK_ACTIONS.hr_manager

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* ── Messages ───────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '24px 20px 16px',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} demoRole={demoRole} />
        ))}

        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingLeft: '0', marginBottom: '12px' }}>
            <div style={{
              width: 32, height: 32, borderRadius: '50%',
              background: '#2d3561', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '14px', fontWeight: 700, color: '#a5b4fc',
            }}>
              F
            </div>
            <span style={{ fontSize: '13px', color: '#555' }}>
              Thinking for {displayName}
            </span>
            <TypingDots />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input + quick actions ──────────────────────────────────────── */}
      <div style={{ padding: '0 16px 16px', background: '#0f1117', borderTop: '1px solid #1a1d2e' }}>

        {/* Text input */}
        <div style={{
          display: 'flex',
          gap: '10px',
          background: '#13151f',
          border: '1px solid #252b42',
          borderRadius: '14px',
          padding: '10px 14px',
          alignItems: 'flex-end',
          marginTop: '12px',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder={`Message as ${displayName}…`}
            rows={1}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#e8e8f0',
              fontSize: '14px',
              resize: 'none',
              lineHeight: '1.5',
              fontFamily: 'inherit',
              maxHeight: '120px',
              overflowY: 'auto',
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            style={{
              width: 36, height: 36,
              borderRadius: '10px',
              background: input.trim() && !loading ? '#2d3561' : '#1a1d2e',
              border: '1px solid',
              borderColor: input.trim() && !loading ? '#4f5fa8' : '#252b42',
              color: input.trim() && !loading ? '#a5b4fc' : '#444',
              cursor: input.trim() && !loading ? 'pointer' : 'default',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
              transition: 'all 0.15s',
            }}
          >
            <SendIcon />
          </button>
        </div>

        {/* Pending approvals alert — HR roles only */}
        {onInboxToggle && pendingCount > 0 && (
          <button
            onClick={onInboxToggle}
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              width: '100%',
              marginTop: '10px',
              padding: '8px 14px',
              background: '#2a1800',
              border: '1px solid #92400e',
              borderLeft: '3px solid #f59e0b',
              borderRadius: '8px',
              color: '#fbbf24',
              fontSize: '13px',
              fontWeight: 500,
              cursor: loading ? 'default' : 'pointer',
              textAlign: 'left',
              fontFamily: 'inherit',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { if (!loading) e.currentTarget.style.background = '#321e00' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#2a1800' }}
          >
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              minWidth: 20, height: 20, borderRadius: '10px',
              background: '#f59e0b', color: '#1a0e00',
              fontSize: '11px', fontWeight: 700, padding: '0 5px',
            }}>
              {pendingCount}
            </span>
            pending approval{pendingCount !== 1 ? 's' : ''} awaiting your decision
            <span style={{ marginLeft: 'auto', fontSize: '11px', color: '#78350f' }}>click to review →</span>
          </button>
        )}

        {/* Quick-action pills */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '10px' }}>
          {actions.map(action => (
            <QuickAction
              key={action}
              label={action}
              disabled={loading}
              onClick={() => handleSend(action)}
            />
          ))}
        </div>

      </div>
    </div>
  )
}

function QuickAction({ label, disabled, onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '5px 12px',
        background: hovered && !disabled ? '#1a1d2e' : 'transparent',
        border: `1px solid ${hovered && !disabled ? '#4f5fa8' : '#252b42'}`,
        borderRadius: '20px',
        color: disabled ? '#333' : hovered ? '#a5b4fc' : '#6b7280',
        fontSize: '12px',
        cursor: disabled ? 'default' : 'pointer',
        transition: 'all 0.15s',
        fontFamily: 'inherit',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}

function TypingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: '3px', alignItems: 'center' }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 5, height: 5,
          borderRadius: '50%',
          background: '#444',
          animation: `bounce 1.2s ${i * 0.2}s infinite`,
        }} />
      ))}
    </span>
  )
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}
