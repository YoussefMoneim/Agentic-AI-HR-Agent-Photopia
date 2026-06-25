import { useCallback, useEffect, useRef, useState } from 'react'
import { approveLeaveRequest, fetchPendingApprovals, rejectLeaveRequest } from '../api.js'

function formatDate(str) {
  if (!str) return ''
  try { return new Date(str).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) }
  catch { return str }
}

function RequestCard({ item, onApproved, onRejected }) {
  const [rejecting, setRejecting] = useState(false)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const ctx = item.context_snapshot || {}
  const dateRange = ctx.start_date && ctx.end_date
    ? `${formatDate(ctx.start_date)} – ${formatDate(ctx.end_date)}`
    : ctx.duration_hours ? `${ctx.duration_hours} hours` : '—'

  async function handleApprove() {
    setBusy(true); setError(null)
    try {
      await approveLeaveRequest(item.leave_request_id || item.request_id)
      onApproved(item.leave_request_id || item.request_id)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  async function handleReject() {
    if (!comment.trim()) { setError('Rejection reason is required.'); return }
    setBusy(true); setError(null)
    try {
      await rejectLeaveRequest(item.leave_request_id || item.request_id, comment.trim())
      onRejected(item.leave_request_id || item.request_id)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{
      background: '#13151f', border: '1px solid #1e2235',
      borderRadius: 10, padding: '14px 16px', marginBottom: 10,
    }}>
      {/* Employee + type row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <div>
          <span style={{ fontWeight: 600, color: '#e8e8f0', fontSize: 14 }}>
            {ctx.employee_name || item.employee_name || 'Unknown'}
          </span>
          <span style={{ color: '#6b7280', fontSize: 12, marginLeft: 8 }}>
            {ctx.employee_code || item.employee_code}
          </span>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px',
          background: '#1e2a4a', color: '#93c5fd', borderRadius: 6,
          border: '1px solid #1e3a7a', whiteSpace: 'nowrap',
        }}>
          {ctx.leave_type || item.leave_type_name || 'Leave'}
        </span>
      </div>

      {/* Date range */}
      <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 4 }}>{dateRange}</div>

      {/* Reason */}
      {ctx.reason && (
        <div style={{
          fontSize: 12, color: '#6b7280',
          background: '#0f1117', borderRadius: 6, padding: '6px 10px',
          marginBottom: 10, fontStyle: 'italic',
          overflow: 'hidden', textOverflow: 'ellipsis',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        }}>
          "{ctx.reason}"
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ fontSize: 12, color: '#f87171', marginBottom: 8 }}>{error}</div>
      )}

      {/* Reject comment input */}
      {rejecting && (
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Reason for rejection (required)"
          rows={2}
          style={{
            width: '100%', boxSizing: 'border-box',
            background: '#0f1117', border: '1px solid #374151',
            borderRadius: 6, color: '#e8e8f0', fontSize: 13,
            padding: '6px 10px', fontFamily: 'inherit',
            resize: 'vertical', marginBottom: 8,
          }}
        />
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8 }}>
        {!rejecting ? (
          <>
            <button
              onClick={handleApprove}
              disabled={busy}
              style={{
                flex: 1, padding: '7px 0', borderRadius: 7, border: 'none',
                background: busy ? '#14532d' : '#166534', color: '#86efac',
                fontSize: 13, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
                fontFamily: 'inherit', transition: 'background 0.15s',
              }}
              onMouseEnter={e => { if (!busy) e.currentTarget.style.background = '#15803d' }}
              onMouseLeave={e => { e.currentTarget.style.background = busy ? '#14532d' : '#166534' }}
            >
              {busy ? 'Approving…' : 'Approve'}
            </button>
            <button
              onClick={() => { setRejecting(true); setError(null) }}
              disabled={busy}
              style={{
                flex: 1, padding: '7px 0', borderRadius: 7,
                background: 'transparent', border: '1px solid #7f1d1d',
                color: '#fca5a5', fontSize: 13, fontWeight: 600,
                cursor: busy ? 'default' : 'pointer', fontFamily: 'inherit',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (!busy) e.currentTarget.style.background = '#450a0a' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              Reject
            </button>
          </>
        ) : (
          <>
            <button
              onClick={handleReject}
              disabled={busy}
              style={{
                flex: 1, padding: '7px 0', borderRadius: 7, border: 'none',
                background: busy ? '#450a0a' : '#7f1d1d', color: '#fca5a5',
                fontSize: 13, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {busy ? 'Rejecting…' : 'Confirm Reject'}
            </button>
            <button
              onClick={() => { setRejecting(false); setComment(''); setError(null) }}
              disabled={busy}
              style={{
                padding: '7px 14px', borderRadius: 7,
                background: 'transparent', border: '1px solid #374151',
                color: '#6b7280', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default function ApprovalInbox({ visible, onCountChange }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const data = await fetchPendingApprovals()
      setItems(data.items || [])
      onCountChange?.(data.count || 0)
    } catch (e) {
      setError(e.message)
    }
  }, [onCountChange])

  useEffect(() => {
    if (!visible) return
    setLoading(true)
    load().finally(() => setLoading(false))
    intervalRef.current = setInterval(load, 15000)
    return () => clearInterval(intervalRef.current)
  }, [visible, load])

  function handleApproved(requestId) {
    setItems(prev => {
      const next = prev.filter(i => (i.leave_request_id || i.request_id) !== requestId)
      onCountChange?.(next.length)
      return next
    })
  }

  function handleRejected(requestId) {
    setItems(prev => {
      const next = prev.filter(i => (i.leave_request_id || i.request_id) !== requestId)
      onCountChange?.(next.length)
      return next
    })
  }

  if (!visible) return null

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
      borderLeft: '1px solid #1a1d2e',
    }}>
      {/* Header */}
      <div style={{
        padding: '14px 18px 12px',
        borderBottom: '1px solid #1a1d2e',
        background: '#0a0c14',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#e8e8f0' }}>Approval Inbox</span>
          {items.length > 0 && (
            <span style={{
              fontSize: 11, fontWeight: 700, padding: '2px 7px',
              background: '#f59e0b', color: '#1a0e00', borderRadius: 10,
            }}>{items.length}</span>
          )}
          <button
            onClick={() => { setLoading(true); load().finally(() => setLoading(false)) }}
            style={{
              marginLeft: 'auto', padding: '3px 10px', borderRadius: 6,
              background: 'transparent', border: '1px solid #252b42',
              color: '#6b7280', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            {loading ? '…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 14px' }}>
        {error && (
          <div style={{ color: '#f87171', fontSize: 13, padding: '8px 0' }}>{error}</div>
        )}
        {!loading && !error && items.length === 0 && (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: '100%', gap: 8, color: '#4b5563',
          }}>
            <span style={{ fontSize: 28 }}>✓</span>
            <span style={{ fontSize: 13 }}>No pending approvals</span>
          </div>
        )}
        {items.map(item => (
          <RequestCard
            key={item.leave_request_id || item.request_id || item.id}
            item={item}
            onApproved={handleApproved}
            onRejected={handleRejected}
          />
        ))}
      </div>
    </div>
  )
}
