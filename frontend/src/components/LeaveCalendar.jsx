import { useEffect, useState } from 'react'
import { getLeaveCalendar } from '../api.js'

const DOW_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

const STATUS_COLORS = {
  pending_approval:          { bg: '#1e2a4a', color: '#93c5fd' },
  pending_top_of_hierarchy:  { bg: '#1e2a4a', color: '#93c5fd' },
  manager_approved:          { bg: '#14352b', color: '#6ee7b7' },
  hr_approved:               { bg: '#14352b', color: '#6ee7b7' },
  cancellation_pending:      { bg: '#2d1a00', color: '#fbbf24' },
}

function formatDay(isoDate) {
  return new Date(isoDate + 'T00:00:00').toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long',
  })
}

function buildGrid(year, month) {
  const firstDow = new Date(year, month - 1, 1).getDay()  // 0=Sun
  const offset   = (firstDow + 6) % 7                      // Mon=0 … Sun=6
  const total    = new Date(year, month, 0).getDate()
  return { offset, total }
}

function dotColor(summary) {
  if (!summary || summary.on_leave_count === 0) return null
  if (summary.over_threshold) return '#ef4444'
  if (summary.percentage >= 16) return '#f59e0b'
  return '#22c55e'
}

function StatusBadge({ status }) {
  const style = STATUS_COLORS[status] || { bg: '#1a1d2e', color: '#6b7280' }
  const label = status?.replace(/_/g, ' ') || 'unknown'
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 5,
      background: style.bg, color: style.color,
      textTransform: 'capitalize',
    }}>
      {label}
    </span>
  )
}

export default function LeaveCalendar({ user }) {
  const todayIso = new Date().toISOString().slice(0, 10)

  const [year,         setYear]         = useState(() => new Date().getFullYear())
  const [month,        setMonth]        = useState(() => new Date().getMonth() + 1)
  const [selectedDay,  setSelectedDay]  = useState(null)
  const [calendarData, setCalendarData] = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)
  const [department,   setDepartment]   = useState(null)

  const isHR = ['hr_manager', 'admin'].includes(user?.role)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setSelectedDay(null)
    getLeaveCalendar(year, month, department)
      .then(setCalendarData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [year, month, department])

  function prevMonth() {
    if (month === 1) { setMonth(12); setYear(y => y - 1) }
    else setMonth(m => m - 1)
  }
  function nextMonth() {
    if (month === 12) { setMonth(1); setYear(y => y + 1) }
    else setMonth(m => m + 1)
  }

  const monthLabel = new Date(year, month - 1).toLocaleString('en-GB', { month: 'long', year: 'numeric' })
  const { offset, total } = buildGrid(year, month)

  // Day detail data
  const dayEvents = selectedDay
    ? (calendarData?.events || []).filter(ev =>
        ev.start_date <= selectedDay && ev.end_date >= selectedDay
      )
    : []
  const daySummary = selectedDay ? calendarData?.daily_summary?.[selectedDay] : null

  const ownEvents   = dayEvents.filter(e => e.is_own)
  const colleagueCount = selectedDay
    ? Math.max(0, (daySummary?.on_leave_count ?? 0) - ownEvents.length)
    : 0

  // Grid cells: offset blanks + day cells
  const cells = []
  for (let i = 0; i < offset; i++) cells.push(null)
  for (let d = 1; d <= total; d++) cells.push(d)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', borderLeft: '1px solid #1a1d2e' }}>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={{
        padding: '14px 18px 12px',
        borderBottom: '1px solid #1a1d2e',
        background: '#0a0c14',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#e8e8f0' }}>Team Calendar</span>
          {isHR && calendarData && (
            <select
              value={department || ''}
              onChange={e => setDepartment(e.target.value || null)}
              style={{
                fontSize: 11, background: '#13151f', color: '#9ca3af',
                border: '1px solid #2a2d40', borderRadius: 5,
                padding: '3px 6px', fontFamily: 'inherit', cursor: 'pointer',
              }}
            >
              <option value=''>All departments</option>
              {(calendarData.departments || []).map(d => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* ── Scrollable body ─────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px 16px' }}>

        {/* Month navigation */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <button onClick={prevMonth} style={navBtnStyle}>←</button>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#e8e8f0' }}>{monthLabel}</span>
          <button onClick={nextMonth} style={navBtnStyle}>→</button>
        </div>

        {/* Error */}
        {error && (
          <div style={{ color: '#f87171', fontSize: 12, textAlign: 'center', padding: '8px 0' }}>{error}</div>
        )}

        {/* Loading shimmer */}
        {loading && (
          <div style={{ color: '#4b5563', fontSize: 12, textAlign: 'center', padding: '8px 0' }}>Loading…</div>
        )}

        {/* Grid */}
        {!loading && !error && (
          <>
            {/* Day-of-week header */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', marginBottom: 2 }}>
              {DOW_LABELS.map(d => (
                <div key={d} style={{ textAlign: 'center', fontSize: 10, color: '#4b5563', fontWeight: 600, padding: '2px 0' }}>
                  {d}
                </div>
              ))}
            </div>

            {/* Day cells */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2 }}>
              {cells.map((day, i) => {
                if (day === null) return <div key={`blank-${i}`} style={{ width: 36, height: 36 }} />
                const iso = `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`
                const summary = calendarData?.daily_summary?.[iso]
                const dot = dotColor(summary)
                const isSelected = iso === selectedDay
                const isToday = iso === todayIso
                return (
                  <div
                    key={iso}
                    onClick={() => setSelectedDay(isSelected ? null : iso)}
                    style={{
                      width: 36, height: 36,
                      display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center',
                      cursor: 'pointer', borderRadius: 6,
                      border: isSelected
                        ? '1.5px solid #7c3aed'
                        : isToday ? '1px solid #4b5563' : '1px solid transparent',
                      background: isSelected ? '#1e1b4b' : 'transparent',
                      fontSize: 12, color: '#e5e7eb',
                      transition: 'background 0.1s',
                    }}
                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = '#13151f' }}
                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
                  >
                    <span>{day}</span>
                    {dot && (
                      <div style={{ width: 5, height: 5, borderRadius: '50%', background: dot, marginTop: 2 }} />
                    )}
                  </div>
                )
              })}
            </div>

            {/* Legend */}
            <div style={{ display: 'flex', gap: 12, marginTop: 10, paddingTop: 8, borderTop: '1px solid #1a1d2e' }}>
              {[
                { color: '#22c55e', label: '1–15%' },
                { color: '#f59e0b', label: '16–24%' },
                { color: '#ef4444', label: '≥25%' },
              ].map(({ color, label }) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
                  <span style={{ fontSize: 10, color: '#6b7280' }}>{label}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── Day detail panel ────────────────────────────────────────── */}
        {selectedDay && calendarData && (
          <div style={{ marginTop: 14 }}>
            {/* Section label */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
            }}>
              <div style={{ flex: 1, height: 1, background: '#1a1d2e' }} />
              <span style={{ fontSize: 11, color: '#6b7280', whiteSpace: 'nowrap' }}>
                {formatDay(selectedDay)}
              </span>
              <div style={{ flex: 1, height: 1, background: '#1a1d2e' }} />
            </div>

            {/* Threshold warning bar (all roles) */}
            {daySummary?.over_threshold && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: '#2d1a00', border: '1px solid #7c3f00',
                borderRadius: 6, padding: '5px 10px', marginBottom: 8,
                fontSize: 12, color: '#fbbf24',
              }}>
                <span>⚠</span>
                <span>
                  {daySummary.on_leave_count} of {daySummary.total_employees} on leave ({daySummary.percentage}%) — exceeds 25% threshold
                </span>
              </div>
            )}

            {/* Employee role view */}
            {user?.role === 'employee' && (
              <div style={{ fontSize: 12 }}>
                {ownEvents.length > 0 ? (
                  ownEvents.map((ev, i) => (
                    <div key={i} style={{
                      background: '#13151f', border: '1px solid #1e2235',
                      borderRadius: 8, padding: '8px 12px', marginBottom: 6,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <span style={{ color: '#e8e8f0', fontWeight: 600 }}>
                          Your leave: {ev.leave_type_label || ev.leave_type_code}
                        </span>
                        <StatusBadge status={ev.status} />
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ color: '#6b7280', marginBottom: 6 }}>You are not on leave this day.</div>
                )}
                {colleagueCount > 0 && (
                  <div style={{ color: '#9ca3af', fontSize: 11, marginTop: 4 }}>
                    {colleagueCount} colleague{colleagueCount !== 1 ? 's' : ''} also on leave this day.
                  </div>
                )}
                {colleagueCount === 0 && daySummary?.on_leave_count === 0 && ownEvents.length === 0 && (
                  <div style={{ color: '#4b5563', fontSize: 11 }}>No leave requests for this day.</div>
                )}
              </div>
            )}

            {/* HR / admin view */}
            {user?.role !== 'employee' && (
              <div>
                {daySummary && !daySummary.over_threshold && (
                  <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 8 }}>
                    {daySummary.on_leave_count} of {daySummary.total_employees} employees on leave ({daySummary.percentage}%)
                  </div>
                )}
                {dayEvents.length === 0 ? (
                  <div style={{ color: '#4b5563', fontSize: 12 }}>No leave requests for this day.</div>
                ) : (
                  dayEvents.map((ev, i) => (
                    <div key={i} style={{
                      background: '#13151f', border: '1px solid #1e2235',
                      borderRadius: 8, padding: '8px 12px', marginBottom: 6,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <div>
                          <span style={{ color: '#e8e8f0', fontWeight: 600, fontSize: 12 }}>
                            {ev.employee_name}
                          </span>
                          {ev.department && (
                            <span style={{ color: '#6b7280', fontSize: 11, marginLeft: 6 }}>
                              {ev.department}
                            </span>
                          )}
                        </div>
                        <StatusBadge status={ev.status} />
                      </div>
                      <div style={{ color: '#9ca3af', fontSize: 11, marginTop: 3 }}>
                        {ev.leave_type_label || ev.leave_type_code}
                        <span style={{ color: '#4b5563', marginLeft: 6 }}>
                          {ev.start_date} → {ev.end_date}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

const navBtnStyle = {
  padding: '3px 10px', borderRadius: 6, border: '1px solid #252b42',
  background: 'transparent', color: '#9ca3af', fontSize: 13,
  cursor: 'pointer', fontFamily: 'inherit',
}
