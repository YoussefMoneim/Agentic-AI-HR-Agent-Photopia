import { useEffect, useRef, useState } from 'react'
import { fetchAuditLog } from '../api.js'

function relativeTime(isoString) {
  if (!isoString) return ''
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000
  if (diff < 5)    return 'just now'
  if (diff < 60)   return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

const TOOL_LABEL = {
  check_leave_balance:             'checked leave balance',
  check_leave_eligibility:         'checked eligibility',
  submit_leave_request:            'submitted leave request',
  get_leave_requests:              'viewed leave requests',
  get_pending_approvals:           'viewed approval queue',
  approve_leave_request:           'approved leave request',
  reject_leave_request:            'rejected leave request',
  cancel_leave_request:            'cancelled leave request',
  get_leave_waiting_status:        'checked waiting status',
  get_employee_data:               'read employee record',
  search_employees:                'searched employees',
  list_employees:                  'listed employees',
  get_leave_balance:               'read leave balance',
  get_employee_summary:            'read employee summary',
  get_employee_documents:          'read document history',
  calculate_end_of_service:        'calculated EOS gratuity',
  generate_salary_certificate:     'generated salary certificate',
  generate_twimc_letter:           'generated TWIMC letter',
  generate_experience_certificate: 'generated experience certificate',
  appropriateness_check:           'raised sensitivity flag',
  share_decision:                  'recorded share decision',
}

const ROLE_STYLE = {
  employee:   { bg: '#1e3a5f', color: '#60a5fa' },
  hr_manager: { bg: '#2d1a4e', color: '#c084fc' },
}

const ACTION_STYLE = {
  data_read:      { bg: '#1a1d2e', color: '#9ca3af', label: 'read' },
  data_write:     { bg: '#2a1e0a', color: '#fbbf24', label: 'write' },
  decision_denied:{ bg: '#2a0a0a', color: '#f87171', label: 'denied' },
  tool_executed:  { bg: '#1a1d2e', color: '#6b7280', label: 'exec' },
}

export default function AuditLog() {
  const [entries, setEntries] = useState([])
  const [expandedId, setExpandedId] = useState(null)
  const [hasNew, setHasNew] = useState(false)
  const [, forceUpdate] = useState(0) // for relative-time refresh
  const seenIds = useRef(new Set())

  async function poll() {
    try {
      const data = await fetchAuditLog(15)
      const fetched = data.entries || []

      const fresh = fetched.filter(e => !seenIds.current.has(String(e.id)))
      if (fresh.length > 0) {
        setHasNew(true)
        setTimeout(() => setHasNew(false), 2500)
      }

      const tagged = fetched.map(e => ({
        ...e,
        isNew: !seenIds.current.has(String(e.id)),
      }))
      fetched.forEach(e => seenIds.current.add(String(e.id)))
      setEntries(tagged)

      // Clear isNew flag after animation completes
      setTimeout(() => {
        setEntries(prev => prev.map(e => ({ ...e, isNew: false })))
      }, 600)
    } catch {
      // Never surface poll errors — demo should keep running
    }
  }

  useEffect(() => {
    poll()
    const pollId = setInterval(poll, 3000)
    // Refresh relative timestamps every 15s without re-fetching
    const tickId = setInterval(() => forceUpdate(n => n + 1), 15000)
    return () => { clearInterval(pollId); clearInterval(tickId) }
  }, [])

  function toggleExpand(id) {
    setExpandedId(prev => (prev === id ? null : id))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0a0c14' }}>

      {/* ── Panel header ────────────────────────────────────────────────── */}
      <div style={{
        height: 48,
        borderBottom: '1px solid #1a1d2e',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        flexShrink: 0,
        gap: '8px',
      }}>
        <PulsingDot active={hasNew} />
        <span style={{ fontSize: '13px', fontWeight: 600, color: '#9ca3af', flex: 1 }}>
          Live Audit Log
        </span>
        <span style={{ fontSize: '11px', color: '#333', fontFamily: 'monospace' }}>
          {entries.length} entries · 3s
        </span>
      </div>

      {/* ── Entry list ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {entries.length === 0 ? (
          <div style={{
            padding: '48px 20px',
            textAlign: 'center',
            color: '#444',
            fontSize: '13px',
            lineHeight: '1.7',
          }}>
            No activity yet.<br />
            <span style={{ color: '#333' }}>Start chatting to see every agent action logged here in real time.</span>
          </div>
        ) : (
          entries.map(entry => (
            <EntryCard
              key={entry.id}
              entry={entry}
              expanded={expandedId === entry.id}
              onToggle={() => toggleExpand(entry.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

function EntryCard({ entry, expanded, onToggle }) {
  const roleStyle = ROLE_STYLE[entry.actor_role] || { bg: '#1a1d2e', color: '#9ca3af' }
  const actionInfo = ACTION_STYLE[entry.action] || ACTION_STYLE.tool_executed
  const isDenied = entry.action === 'decision_denied'
  const isSuccess = entry.outcome === 'success'
  const summary = entry.result_summary || ''
  const truncated = summary.length > 80 ? summary.slice(0, 80) + '…' : summary
  const toolLabel = TOOL_LABEL[entry.tool_name]

  const baseBg = isDenied ? '#1a0a0a' : '#13151f'
  const baseBorder = isDenied ? '#7f1d1d' : '#1a1d2e'
  const hoverBg = isDenied ? '#1f0c0c' : '#161820'
  const hoverBorder = isDenied ? '#991b1b' : '#252b42'

  return (
    <div
      onClick={onToggle}
      style={{
        background: baseBg,
        border: `1px solid ${baseBorder}`,
        borderLeft: isDenied ? '3px solid #7f1d1d' : `1px solid ${baseBorder}`,
        borderRadius: '8px',
        padding: '10px 12px',
        marginBottom: '5px',
        cursor: 'pointer',
        animation: entry.isNew ? 'auditSlideIn 0.35s ease-out' : 'none',
        userSelect: 'none',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = hoverBorder; e.currentTarget.style.background = hoverBg }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = baseBorder; e.currentTarget.style.background = baseBg }}
    >
      {/* Row 1: tool name + badges */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 0 }}>
          <span style={{
            fontSize: '12px',
            fontWeight: 600,
            color: '#d1d5db',
            fontFamily: 'monospace',
            letterSpacing: '-0.2px',
            display: 'block',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {entry.tool_name}
          </span>
          {toolLabel && (
            <span style={{ fontSize: '10px', color: '#4b5563', display: 'block', marginTop: '1px' }}>
              {toolLabel}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          <Badge bg={roleStyle.bg} color={roleStyle.color}>
            {entry.actor_role?.replace('_', ' ') || 'unknown'}
          </Badge>
          <Badge bg={actionInfo.bg} color={actionInfo.color}>
            {actionInfo.label}
          </Badge>
        </div>
      </div>

      {/* Row 2: outcome + timestamp */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '5px' }}>
        <span style={{
          fontSize: '12px',
          color: isSuccess ? '#4ade80' : '#f87171',
          fontWeight: 500,
        }}>
          {isSuccess ? '✓' : '✗'} {entry.outcome}
        </span>
        <span style={{ fontSize: '11px', color: '#333' }}>·</span>
        <span style={{ fontSize: '11px', color: '#4b5563' }}>
          {relativeTime(entry.created_at)}
        </span>
      </div>

      {/* Row 3: result summary */}
      {summary && (
        <div style={{
          marginTop: '6px',
          fontSize: '11px',
          color: '#4b5563',
          fontFamily: 'monospace',
          wordBreak: 'break-all',
          lineHeight: '1.5',
          transition: 'color 0.15s',
        }}>
          {expanded ? summary : truncated}
          {summary.length > 80 && (
            <span style={{ color: '#374151', marginLeft: '4px' }}>
              {expanded ? '▲' : '▼'}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function Badge({ bg, color, children }) {
  return (
    <span style={{
      fontSize: '10px',
      fontWeight: 600,
      padding: '2px 6px',
      borderRadius: '4px',
      background: bg,
      color: color,
      textTransform: 'uppercase',
      letterSpacing: '0.4px',
      whiteSpace: 'nowrap',
      lineHeight: '1.4',
    }}>
      {children}
    </span>
  )
}

function PulsingDot({ active }) {
  return (
    <span style={{
      display: 'inline-block',
      width: 7, height: 7,
      borderRadius: '50%',
      background: active ? '#4ade80' : '#1f3d1f',
      boxShadow: active ? '0 0 6px #4ade8066' : 'none',
      animation: active ? 'pulseGlow 1s ease-in-out infinite' : 'none',
      transition: 'background 0.4s, box-shadow 0.4s',
      flexShrink: 0,
    }} />
  )
}
