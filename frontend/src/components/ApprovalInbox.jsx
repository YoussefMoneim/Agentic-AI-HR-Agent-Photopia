import { useCallback, useEffect, useRef, useState } from 'react'
import {
  approveLeaveCancellation, approveLeaveRequest, checkLeaveConstraints,
  fetchPendingApprovals, getPendingCancellations, rejectLeaveRequest,
} from '../api.js'

function formatDate(str) {
  if (!str) return ''
  try {
    return new Date(str + 'T00:00:00').toLocaleDateString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric',
    })
  } catch { return str }
}

// ── Button primitives ─────────────────────────────────────────────────────────

function GreenBtn({ onClick, disabled, children }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1, padding: '7px 0', borderRadius: 7, border: 'none',
        background: disabled ? '#14532d' : '#166534', color: '#86efac',
        fontSize: 13, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
        fontFamily: 'inherit', transition: 'background 0.15s',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = '#15803d' }}
      onMouseLeave={e => { e.currentTarget.style.background = disabled ? '#14532d' : '#166534' }}
    >
      {children}
    </button>
  )
}

function RedBtn({ onClick, disabled, children, outline }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        flex: 1, padding: '7px 0', borderRadius: 7,
        background: outline ? 'transparent' : (disabled ? '#450a0a' : '#7f1d1d'),
        border: outline ? '1px solid #7f1d1d' : 'none',
        color: '#fca5a5', fontSize: 13, fontWeight: 600,
        cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit',
        transition: 'all 0.15s',
      }}
      onMouseEnter={e => { if (!disabled && outline) e.currentTarget.style.background = '#450a0a' }}
      onMouseLeave={e => { if (outline) e.currentTarget.style.background = 'transparent' }}
    >
      {children}
    </button>
  )
}

function GhostBtn({ onClick, disabled, children }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '7px 14px', borderRadius: 7,
        background: 'transparent', border: '1px solid #374151',
        color: '#6b7280', fontSize: 13, cursor: disabled ? 'default' : 'pointer',
        fontFamily: 'inherit',
      }}
    >
      {children}
    </button>
  )
}

// ── RequestCard ───────────────────────────────────────────────────────────────

function RequestCard({ item, onApproved, onRejected }) {
  // phase: 'idle' | 'checking' | 'override' | 'blocked' | 'approving'
  //        | 'rejecting' | 'rejecting-busy'
  const [phase, setPhase] = useState('idle')
  const [constraintReason, setConstraintReason] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [rejectComment, setRejectComment] = useState('')
  const [error, setError] = useState(null)

  const requestId = item.leave_request_id
  const busy = phase === 'checking' || phase === 'approving' || phase === 'rejecting-busy'

  const dateRange = item.start_date && item.end_date
    ? `${formatDate(item.start_date)} – ${formatDate(item.end_date)}`
    : item.duration_hours ? `${item.duration_hours} hours` : '—'

  const dayLabel = item.days_requested
    ? `${item.days_requested} day${item.days_requested !== 1 ? 's' : ''}`
    : null

  const balanceAfter = item.balance_remaining != null ? item.balance_remaining : null

  async function handleApproveClick() {
    setPhase('checking')
    setError(null)
    try {
      const check = await checkLeaveConstraints(requestId)
      if (check.verdict === 'blocked') {
        setConstraintReason(check.reason)
        setPhase('blocked')
      } else if (check.verdict === 'requires_override') {
        setConstraintReason(check.reason)
        setPhase('override')
      } else {
        await doApprove(null)
      }
    } catch (e) {
      setError(e.message)
      setPhase('idle')
    }
  }

  async function doApprove(overrideRsn) {
    setPhase('approving')
    setError(null)
    try {
      await approveLeaveRequest(requestId, null, overrideRsn)
      onApproved(requestId)
    } catch (e) {
      setError(e.message)
      setPhase(overrideRsn ? 'override' : 'idle')
    }
  }

  async function handleReject() {
    if (!rejectComment.trim()) { setError('Rejection reason is required.'); return }
    setPhase('rejecting-busy')
    setError(null)
    try {
      await rejectLeaveRequest(requestId, rejectComment.trim())
      onRejected(requestId)
    } catch (e) {
      setError(e.message)
      setPhase('rejecting')
    }
  }

  return (
    <div style={{
      background: '#13151f', border: '1px solid #1e2235',
      borderRadius: 10, padding: '14px 16px', marginBottom: 10,
    }}>

      {/* Row 1: name + leave type badge */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
        <div>
          <span style={{ fontWeight: 600, color: '#e8e8f0', fontSize: 14 }}>
            {item.employee_name || 'Unknown'}
          </span>
          <span style={{ color: '#6b7280', fontSize: 12, marginLeft: 8 }}>
            {item.employee_code}
          </span>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px',
          background: '#1e2a4a', color: '#93c5fd', borderRadius: 6,
          border: '1px solid #1e3a7a', whiteSpace: 'nowrap', flexShrink: 0,
        }}>
          {item.leave_type_name || 'Leave'}
        </span>
      </div>

      {/* Row 2: dates + days */}
      <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 3 }}>
        {dateRange}
        {dayLabel && <span style={{ color: '#6b7280' }}> &bull; {dayLabel}</span>}
      </div>

      {/* Row 3: balance after approval */}
      {balanceAfter != null && (
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 3 }}>
          Balance after approval:{' '}
          <span style={{ color: balanceAfter < 3 ? '#f59e0b' : '#9ca3af', fontWeight: 500 }}>
            {balanceAfter} day{balanceAfter !== 1 ? 's' : ''} remaining
          </span>
        </div>
      )}

      {/* Row 4: reason */}
      {item.reason ? (
        <div style={{
          fontSize: 12, color: '#6b7280',
          background: '#0f1117', borderRadius: 6, padding: '5px 10px',
          marginBottom: 3, fontStyle: 'italic',
          overflow: 'hidden', textOverflow: 'ellipsis',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        }}>
          Reason: &ldquo;{item.reason}&rdquo;
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#374151', marginBottom: 3 }}>Reason: Not provided</div>
      )}

      {/* Row 5: submitted date */}
      {item.submitted_at && (
        <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 10 }}>
          Submitted: {formatDate(item.submitted_at)}
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ fontSize: 12, color: '#f87171', marginBottom: 8 }}>{error}</div>
      )}

      {/* ── Constraint panels ─────────────────────────────────── */}

      {phase === 'override' && (
        <div style={{
          background: '#2d1a00', border: '1px solid #7c3f00',
          borderRadius: 8, padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#fbbf24', marginBottom: 4 }}>
            ⚠ Approval Warning
          </div>
          <div style={{ fontSize: 12, color: '#fde68a', marginBottom: 8 }}>{constraintReason}</div>
          <label style={{ fontSize: 11, color: '#9ca3af', display: 'block', marginBottom: 4 }}>
            Override reason (required):
          </label>
          <textarea
            value={overrideReason}
            onChange={e => setOverrideReason(e.target.value)}
            placeholder="Explain why you are approving despite the policy constraint…"
            rows={2}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: '#0f1117', border: '1px solid #374151',
              borderRadius: 6, color: '#e8e8f0', fontSize: 12,
              padding: '6px 10px', fontFamily: 'inherit', resize: 'vertical', marginBottom: 8,
            }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <GreenBtn
              onClick={() => doApprove(overrideReason)}
              disabled={!overrideReason.trim() || phase === 'approving'}
            >
              {phase === 'approving' ? 'Approving…' : 'Approve anyway — log my decision'}
            </GreenBtn>
            <GhostBtn
              onClick={() => { setPhase('idle'); setOverrideReason(''); setError(null) }}
              disabled={phase === 'approving'}
            >
              Cancel
            </GhostBtn>
          </div>
        </div>
      )}

      {phase === 'blocked' && (
        <div style={{
          background: '#1a0000', border: '1px solid #7f1d1d',
          borderRadius: 8, padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#f87171', marginBottom: 4 }}>
            ✗ Cannot Approve
          </div>
          <div style={{ fontSize: 12, color: '#fca5a5', marginBottom: 4 }}>{constraintReason}</div>
          <div style={{ fontSize: 11, color: '#6b7280' }}>
            This leave cannot be approved under current policy. Please reject or contact HR.
          </div>
        </div>
      )}

      {/* ── Reject textarea ───────────────────────────────────── */}
      {(phase === 'rejecting' || phase === 'rejecting-busy') && (
        <textarea
          value={rejectComment}
          onChange={e => setRejectComment(e.target.value)}
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

      {/* ── Action buttons ────────────────────────────────────── */}
      {phase !== 'override' && (
        <div style={{ display: 'flex', gap: 8 }}>
          {phase === 'rejecting' || phase === 'rejecting-busy' ? (
            <>
              <RedBtn onClick={handleReject} disabled={phase === 'rejecting-busy'}>
                {phase === 'rejecting-busy' ? 'Rejecting…' : 'Confirm Reject'}
              </RedBtn>
              <GhostBtn
                onClick={() => { setPhase('idle'); setRejectComment(''); setError(null) }}
                disabled={phase === 'rejecting-busy'}
              >
                Cancel
              </GhostBtn>
            </>
          ) : (
            <>
              {phase !== 'blocked' && (
                <GreenBtn onClick={handleApproveClick} disabled={busy}>
                  {phase === 'checking' ? 'Checking…' : phase === 'approving' ? 'Approving…' : 'Approve'}
                </GreenBtn>
              )}
              <RedBtn
                onClick={() => { setPhase('rejecting'); setError(null) }}
                disabled={busy}
                outline
              >
                Reject
              </RedBtn>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── CancellationCard ──────────────────────────────────────────────────────────

function CancellationCard({ item, onApproved }) {
  const [consumedDays, setConsumedDays] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const requestedAt = item.cancellation_requested_at
    ? new Date(item.cancellation_requested_at).toLocaleString('en-GB', {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      })
    : null

  async function handleApprove() {
    setBusy(true); setError(null)
    try {
      const days = consumedDays !== '' ? parseFloat(consumedDays) : null
      await approveLeaveCancellation(item.id, days)
      onApproved(item.id)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{
      background: '#1a0e00', border: '1px solid #7c3f00',
      borderRadius: 10, padding: '14px 16px', marginBottom: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <div>
          <span style={{ fontWeight: 600, color: '#e8e8f0', fontSize: 14 }}>
            {item.employee_name || 'Unknown'}
          </span>
          <span style={{ color: '#6b7280', fontSize: 12, marginLeft: 8 }}>
            {item.employee_code}
          </span>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px',
          background: '#2d1a00', color: '#fbbf24', borderRadius: 6,
          border: '1px solid #7c3f00', whiteSpace: 'nowrap',
        }}>
          Cancellation Request
        </span>
      </div>

      <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 2 }}>
        {item.leave_type_name} &bull; {formatDate(item.start_date)} – {formatDate(item.end_date)}
        {item.days_requested ? ` • ${item.days_requested} days` : ''}
      </div>

      {item.cancellation_reason && (
        <div style={{
          fontSize: 12, color: '#6b7280',
          background: '#0f1117', borderRadius: 6, padding: '6px 10px',
          marginBottom: 8, fontStyle: 'italic',
        }}>
          &ldquo;{item.cancellation_reason}&rdquo;
        </div>
      )}

      {requestedAt && (
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 10 }}>
          Requested {requestedAt}
        </div>
      )}

      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 11, color: '#9ca3af', display: 'block', marginBottom: 4 }}>
          Days already taken (leave blank if leave has not started)
        </label>
        <input
          type="number"
          min="0"
          max={item.days_requested || undefined}
          step="0.5"
          value={consumedDays}
          onChange={e => setConsumedDays(e.target.value)}
          placeholder="e.g. 2"
          style={{
            width: 80, padding: '5px 8px', borderRadius: 6,
            background: '#0f1117', border: '1px solid #374151',
            color: '#e8e8f0', fontSize: 13, fontFamily: 'inherit',
          }}
        />
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#f87171', marginBottom: 8 }}>{error}</div>
      )}

      <button
        onClick={handleApprove}
        disabled={busy}
        style={{
          padding: '7px 16px', borderRadius: 7, border: 'none',
          background: busy ? '#7c3f00' : '#92400e', color: '#fde68a',
          fontSize: 13, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
          fontFamily: 'inherit',
        }}
      >
        {busy ? 'Approving…' : 'Approve Cancellation'}
      </button>
    </div>
  )
}

// ── ApprovalInbox ─────────────────────────────────────────────────────────────

export default function ApprovalInbox({ visible, onCountChange }) {
  const [items, setItems] = useState([])
  const [cancellations, setCancellations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const [approvalsData, cancelsData] = await Promise.allSettled([
        fetchPendingApprovals(),
        getPendingCancellations(),
      ])
      if (approvalsData.status === 'fulfilled') {
        setItems(approvalsData.value.items || [])
      }
      if (cancelsData.status === 'fulfilled') {
        setCancellations(cancelsData.value.pending_cancellations || [])
      }
      const approvalCount = approvalsData.status === 'fulfilled' ? (approvalsData.value.count || 0) : 0
      const cancelCount = cancelsData.status === 'fulfilled' ? (cancelsData.value.count || 0) : 0
      onCountChange?.(approvalCount + cancelCount)
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
      const next = prev.filter(i => i.leave_request_id !== requestId)
      onCountChange?.(next.length + cancellations.length)
      return next
    })
  }

  function handleRejected(requestId) {
    setItems(prev => {
      const next = prev.filter(i => i.leave_request_id !== requestId)
      onCountChange?.(next.length + cancellations.length)
      return next
    })
  }

  function handleCancellationApproved(requestId) {
    setCancellations(prev => {
      const next = prev.filter(i => i.id !== requestId)
      onCountChange?.(items.length + next.length)
      return next
    })
  }

  const totalCount = items.length + cancellations.length

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
          {totalCount > 0 && (
            <span style={{
              fontSize: 11, fontWeight: 700, padding: '2px 7px',
              background: '#f59e0b', color: '#1a0e00', borderRadius: 10,
            }}>{totalCount}</span>
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
        {!loading && !error && totalCount === 0 && (
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
            key={item.leave_request_id || item.id}
            item={item}
            onApproved={handleApproved}
            onRejected={handleRejected}
          />
        ))}

        {cancellations.length > 0 && (
          <>
            {items.length > 0 && (
              <div style={{
                fontSize: 11, letterSpacing: 2, textTransform: 'uppercase',
                color: '#4b5563', margin: '12px 0 8px',
              }}>
                Cancellation Requests
              </div>
            )}
            {cancellations.map(item => (
              <CancellationCard
                key={item.id}
                item={item}
                onApproved={handleCancellationApproved}
              />
            ))}
          </>
        )}
      </div>
    </div>
  )
}
