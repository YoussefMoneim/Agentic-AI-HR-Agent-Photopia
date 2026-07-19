import { useEffect, useRef, useState } from 'react'
import { fetchPendingCount, sendChat } from '../api.js'
import { uploadOnboardingDocument } from '../onboarding/uploadApi.js'
import AgentPicker from './AgentPicker/index.jsx'
import MessageBubble from './MessageBubble.jsx'
import OnboardingUploadButton from '../onboarding/OnboardingUploadButton.jsx'

// HR-specific quick actions only — no generic content-gen buttons.
// "Set up your agent" is HR/admin-only and rendered separately (see
// SetupAgentButton below), matching the backend's own role gate.
const QUICK_ACTIONS = {
  employee: [
    'Ask a policy question',
    'Submit leave',
  ],
  hr_manager: [
    'Ask a policy question',
    'View pending approvals',
  ],
}

const WELCOME = {
  employee:   (name) => `Hello ${name}! I can check your leave balance, submit leave requests, and generate official documents. What would you like to do?`,
  hr_manager: (name) => `Hello ${name}! I can show pending approvals, look up employee data, and generate official HR documents. What would you like to do?`,
}

// `thread` ({ sessionId, messages, awaitingUpload }) and `onThreadChange`
// make this a controlled-ish component: App.jsx owns the actual thread list
// (and persists it), this component just mounts fresh per-thread (parent
// renders it with key={thread.id}, so switching threads remounts it with
// that thread's own saved state) and reports every change back upward so
// switching away and back — or a page refresh — doesn't lose it.
export default function ChatInterface({ thread, onThreadChange, demoRole, displayName: fullName, onInboxToggle }) {
  const displayName = (fullName || '').split(' ')[0] || 'there'
  const welcome = (WELCOME[demoRole] || WELCOME.hr_manager)(displayName)
  const [messages, setMessages] = useState(() => thread.messages ?? [
    { id: 0, role: 'agent', text: welcome, documents: [] },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => thread.sessionId ?? null)
  const [awaitingUpload, setAwaitingUpload] = useState(() => thread.awaitingUpload ?? false)
  const [pendingCount, setPendingCount] = useState(0)
  // Files the user has attached but not yet sent — staged here rather than
  // uploaded on selection, so they can write their message, attach one or
  // several files, remove any before sending, and send text + all files
  // together in one action (each file still goes through its own upload
  // call and its own content classification — there's just one composer
  // action bundling them, not one combined backend request).
  const [stagedFiles, setStagedFiles] = useState([])
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Push every change up to App.jsx's per-thread record — the only way this
  // thread's own conversation survives switching to another thread and back.
  useEffect(() => {
    onThreadChange({ messages, sessionId, awaitingUpload })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, sessionId, awaitingUpload])

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
    const files = stagedFiles
    if ((!msg && !files.length) || loading) return
    setInput('')
    setStagedFiles([])

    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', text: msg, documents: [], attachedFileNames: files.map(f => f.name) },
    ])
    setLoading(true)

    try {
      // Text and each file are separate backend calls either way (there's
      // no combined endpoint) — sent in the order the user composed them:
      // text first, then each attachment in turn, all against the same
      // session. Each file gets its own reply, since each is independently
      // classified and may fill a different slot (or be rejected).
      if (msg) {
        const data = await sendChat(msg, sessionId, demoRole)
        if (data.session_id && !sessionId) {
          setSessionId(data.session_id)
        }
        setAwaitingUpload(!!data.awaiting_upload)
        setMessages(prev => [
          ...prev,
          { id: crypto.randomUUID(), role: 'agent', text: data.response, documents: data.documents || [] },
        ])
      }
      for (const file of files) {
        const data = await uploadOnboardingDocument(sessionId, file)
        setAwaitingUpload(!!data.awaiting_upload)
        setMessages(prev => [
          ...prev,
          { id: crypto.randomUUID(), role: 'agent', text: data.response, documents: data.documents || [] },
        ])
      }
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { id: crypto.randomUUID(), role: 'agent', text: `Something went wrong: ${err.message}`, documents: [] },
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

  function handleFilesSelected(files) {
    setStagedFiles(prev => [...prev, ...files])
  }

  function handleRemoveStagedFile(index) {
    setStagedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const actions = QUICK_ACTIONS[demoRole] || QUICK_ACTIONS.hr_manager
  // Must match agent/onboarding.py's own gate exactly — hr_staff is part of
  // HR_ROLES (gets onInboxToggle) but NOT allowed to set up an agent, so
  // this can't just reuse onInboxToggle's truthiness.
  const canSetUpAgent = demoRole === 'hr_manager' || demoRole === 'admin'

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

        {/* Agent picker */}
        <div style={{ marginTop: '12px' }}>
          <AgentPicker />
        </div>

        {/* Staged files — attached but not yet sent, each individually
            removable before Send */}
        {stagedFiles.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '10px' }}>
            {stagedFiles.map((file, index) => (
              <div key={`${file.name}-${index}`} style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '6px 10px',
                background: '#1a1d2e', border: '1px solid #252b42', borderRadius: '8px',
                fontSize: '12px', color: '#a5b4fc',
              }}>
                <PaperclipIconSmall />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {file.name}
                </span>
                <button
                  onClick={() => handleRemoveStagedFile(index)}
                  disabled={loading}
                  title="Remove attachment"
                  style={{
                    background: 'none', border: 'none', color: '#6b7280',
                    cursor: loading ? 'default' : 'pointer', fontSize: '15px',
                    lineHeight: 1, padding: '2px 4px', fontFamily: 'inherit',
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Text input */}
        <div style={{
          display: 'flex',
          gap: '10px',
          background: '#13151f',
          border: '1px solid #252b42',
          borderRadius: '14px',
          padding: '10px 14px',
          alignItems: 'flex-end',
          marginTop: '10px',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="What would you like to do?"
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
          {/* Always rendered AND always clickable (except mid-request) —
              never gated behind awaitingUpload. Selecting file(s) just
              stages them (handleFilesSelected) — nothing uploads until
              Send, same as typed text, so the user can compose a message,
              attach one or more files, remove any if they change their
              mind, and send everything together. */}
          <OnboardingUploadButton
            disabled={loading}
            onFilesSelected={handleFilesSelected}
          />
          <button
            onClick={() => handleSend()}
            disabled={(!input.trim() && !stagedFiles.length) || loading}
            style={{
              width: 36, height: 36,
              borderRadius: '10px',
              background: (input.trim() || stagedFiles.length) && !loading ? '#2d3561' : '#1a1d2e',
              border: '1px solid',
              borderColor: (input.trim() || stagedFiles.length) && !loading ? '#4f5fa8' : '#252b42',
              color: (input.trim() || stagedFiles.length) && !loading ? '#a5b4fc' : '#444',
              cursor: (input.trim() || stagedFiles.length) && !loading ? 'pointer' : 'default',
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

        {/* "Set up your agent" — HR/admin only, visually distinct from the
            regular quick-action pills below (same handleSend call, just
            more prominent, matching the backend's own role gate). */}
        {canSetUpAgent && (
          <button
            onClick={() => handleSend('Set up your agent')}
            disabled={loading}
            style={{
              display: 'flex', alignItems: 'center', gap: '8px',
              width: '100%', marginTop: '10px', padding: '10px 14px',
              background: '#1e1a4e', border: '1px solid #4f46e5',
              borderRadius: '10px', color: '#c7d2fe',
              fontSize: '13px', fontWeight: 600,
              cursor: loading ? 'default' : 'pointer',
              fontFamily: 'inherit', transition: 'background 0.15s',
            }}
            onMouseEnter={e => { if (!loading) e.currentTarget.style.background = '#28226b' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#1e1a4e' }}
          >
            <SetupIcon />
            Set up your agent
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

function PaperclipIconSmall() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
      <path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 015 5l-9.2 9.19a1.5 1.5 0 01-2.12-2.12l8.49-8.48" />
    </svg>
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

function SetupIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2l2.4 7.2H22l-6 4.4 2.3 7.2-6.3-4.5L5.7 21l2.3-7.2-6-4.4h7.6z" />
    </svg>
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
