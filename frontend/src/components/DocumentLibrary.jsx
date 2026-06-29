import { useCallback, useEffect, useRef, useState } from 'react'
import {
  checkDocumentShare,
  getDemoDocuments,
  listEmployees,
  pasteDemoDocument,
  recordShareDecision,
  resetDemoDocuments,
  uploadDemoDocument,
} from '../api.js'

const ROLE_DISPLAY = {
  employee:   'Employee',
  hr_staff:   'HR Staff',
  hr_manager: 'HR Manager',
  admin:      'Admin',
}

const SENSITIVITY_LABELS = {
  salary:      'salary figures',
  national_id: 'national ID number',
  medical:     'medical information',
  performance: 'performance records',
  financial:   'financial data',
}

const SAMPLE_TEXTS = [
  {
    label: 'Salary + national ID',
    text: `Employee: Ahmed Hassan\nBasic salary: EGP 45,000 per month\nHousing allowance: EGP 5,000\nNational ID: 29901011234567\nDepartment: Engineering`,
  },
  {
    label: 'Medical report',
    text: `Sick leave medical report — Dr. Khalid Mansour\nPatient diagnosis: acute respiratory infection\nPrescribed treatment: 5 days rest, antibiotics\nRecommended sick leave: 3 working days`,
  },
  {
    label: 'Clean document',
    text: `Team meeting agenda — Q3 planning\nTuesday July 8th, 10:00 AM, Conference Room B\nAttendees: Engineering and Product teams\nTopics: roadmap review, sprint planning, retrospective`,
  },
  {
    label: 'Performance record',
    text: `Performance Improvement Plan — Confidential\nEmployee: Omar Alsayed\nReview period: Q2 2026\nCurrent rating: Partially meets expectations\nManager: Nourhan Hosny — Warning letter issued`,
  },
]

// ── Styles ─────────────────────────────────────────────────────────────────────

const s = {
  root: {
    height: '100%', overflowY: 'auto', padding: '20px 16px',
    background: '#0f1117', color: '#e8e8f0', fontFamily: 'inherit',
  },
  sectionTitle: {
    fontSize: 11, letterSpacing: 2, textTransform: 'uppercase',
    color: '#4b5563', marginBottom: 12, marginTop: 4,
  },
  dropZone: {
    border: '2px dashed #2a2d40', borderRadius: 10, padding: '24px 16px',
    textAlign: 'center', cursor: 'pointer', transition: 'border-color 0.15s',
    marginBottom: 12,
  },
  dropZoneActive: { borderColor: '#6c7aff' },
  tabRow: { display: 'flex', gap: 8, marginBottom: 14 },
  tab: (active) => ({
    padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
    border: `1px solid ${active ? '#4f46e5' : '#1a1d2e'}`,
    background: active ? '#4f46e5' : 'transparent',
    color: active ? '#fff' : '#6b7280', cursor: 'pointer', fontFamily: 'inherit',
  }),
  textarea: {
    width: '100%', boxSizing: 'border-box', background: '#13151f',
    border: '1px solid #1a1d2e', borderRadius: 8, padding: '10px 12px',
    color: '#e8e8f0', fontSize: 13, fontFamily: 'monospace', resize: 'vertical',
    minHeight: 90, outline: 'none', marginBottom: 8,
  },
  btn: (variant = 'primary') => ({
    padding: '8px 16px', borderRadius: 7, fontSize: 13, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
    background: variant === 'primary' ? '#4f46e5'
      : variant === 'danger' ? '#dc2626'
      : variant === 'ghost' ? 'transparent'
      : '#232548',
    color: variant === 'ghost' ? '#6b7280' : '#fff',
    border: variant === 'ghost' ? '1px solid #1a1d2e' : 'none',
  }),
  card: {
    background: '#13151f', border: '1px solid #1a1d2e', borderRadius: 10,
    padding: '14px 16px', marginBottom: 10,
  },
  badge: (sensitive) => ({
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
    background: sensitive ? '#2d0f0f' : '#0a2a0a',
    color: sensitive ? '#fca5a5' : '#86efac',
    border: `1px solid ${sensitive ? '#7f1d1d' : '#166534'}`,
    marginBottom: 6,
  }),
  divider: {
    borderTop: '1px solid #1a1d2e', margin: '12px 0',
  },
  warningBox: {
    background: '#2d0f0f', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '14px 16px', marginTop: 10, fontSize: 13, color: '#fca5a5',
    lineHeight: 1.5,
  },
  successBox: {
    background: '#0a2a0a', border: '1px solid #166534', borderRadius: 8,
    padding: '14px 16px', marginTop: 10, fontSize: 13, color: '#86efac',
    lineHeight: 1.5,
  },
  spinner: {
    display: 'inline-block', width: 14, height: 14,
    border: '2px solid #2a2d40', borderTop: '2px solid #6c7aff',
    borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    marginRight: 6, verticalAlign: 'middle',
  },
}

// ── SharePanel — always-visible share flow for one document card ───────────────

function SharePanel({ docId, userDisplayName, sensitivityTypes }) {
  const [employees, setEmployees] = useState([])
  const [loadingPeople, setLoadingPeople] = useState(true)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null) // null | {employee_code, full_name, role, ...} | 'external'
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState(null)   // null | {flagged, event_id, ...}
  const [decided, setDecided] = useState(null) // null | 'proceeded' | 'cancelled'
  const [deciding, setDeciding] = useState(false)
  const [sharedAt, setSharedAt] = useState(null)
  const [externalEmail, setExternalEmail] = useState('')

  useEffect(() => {
    listEmployees()
      .then(data => setEmployees(data.employees || []))
      .catch(() => {})
      .finally(() => setLoadingPeople(false))
  }, [])

  const filtered = search.trim()
    ? employees.filter(e =>
        e.full_name.toLowerCase().includes(search.toLowerCase()) ||
        (e.department || '').toLowerCase().includes(search.toLowerCase())
      )
    : employees

  function selectPerson(emp) {
    setSelected(emp)
    setSearch('')
    setResult(null)
    setDecided(null)
  }

  function selectExternal() {
    setSelected('external')
    setSearch('')
    setResult(null)
    setDecided(null)
    setExternalEmail('')
  }

  async function handleShare() {
    if (!selected) return
    setChecking(true)
    setResult(null)
    setDecided(null)
    try {
      const isExternal = selected === 'external'
      const data = await checkDocumentShare(docId, {
        recipientEmployeeCode: isExternal ? null : selected.employee_code,
        recipientRole: isExternal ? null : selected.role,
        recipientName: isExternal ? externalEmail : selected.full_name,
      })
      setResult(data)
    } catch (err) {
      setResult({ error: err.message })
    } finally {
      setChecking(false)
    }
  }

  async function handleDecide(decision) {
    if (!result?.event_id) return
    setDeciding(true)
    try {
      await recordShareDecision(result.event_id, decision)
      if (decision === 'proceeded') setSharedAt(new Date().toLocaleTimeString())
      setDecided(decision)
    } finally {
      setDeciding(false)
    }
  }

  function reset() {
    setSelected(null)
    setResult(null)
    setDecided(null)
    setSharedAt(null)
    setExternalEmail('')
  }

  const recipientLabel = selected === 'external'
    ? (externalEmail || 'External recipient')
    : (selected?.full_name || '')

  const roleLabel = selected === 'external'
    ? 'external recipient'
    : (ROLE_DISPLAY[selected?.role] || selected?.role || '')

  const typesLabel = sensitivityTypes.length > 0
    ? sensitivityTypes.map(t => SENSITIVITY_LABELS[t] || t).join(', ')
    : ''

  const selectedLabel = selected === 'external'
    ? 'External (outside company)'
    : selected
      ? `${selected.full_name} · ${ROLE_DISPLAY[selected.role] || selected.role}`
      : null

  // ── Post-decision states ─────────────────────────────────────────────────────

  if (decided === 'proceeded') {
    return (
      <div>
        <hr style={s.divider} />
        <div style={s.successBox}>
          <strong>✓ Shared and logged</strong>
          <div style={{ marginTop: 6 }}>
            Shared with <strong>{recipientLabel}</strong> at {sharedAt}
          </div>
          <div style={{ fontSize: 11, color: '#4ade80', marginTop: 4 }}>
            Decision recorded under <strong>{userDisplayName}</strong>
          </div>
        </div>
        <button style={{ ...s.btn('ghost'), marginTop: 8, fontSize: 11 }} onClick={reset}>
          Share again
        </button>
      </div>
    )
  }

  // ── Picker + share flow ──────────────────────────────────────────────────────

  return (
    <div>
      <hr style={s.divider} />

      {/* Person selector */}
      {selected && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div style={{
            flex: 1, background: '#1a1d2e', border: '1px solid #2a2d40',
            borderRadius: 7, padding: '7px 10px', fontSize: 13, color: '#e8e8f0',
          }}>
            {selectedLabel}
          </div>
          <button style={{ ...s.btn('ghost'), fontSize: 11 }} onClick={reset}>
            Change
          </button>
        </div>
      )}
      {selected === 'external' && (
        <input
          type="email"
          style={{ ...s.textarea, minHeight: 'unset', marginTop: 0, marginBottom: 8, padding: '7px 10px', fontSize: 13 }}
          placeholder="Recipient email address"
          value={externalEmail}
          onChange={e => setExternalEmail(e.target.value)}
          autoFocus
        />
      )}
      {!selected && (
        <div style={{ marginBottom: 10 }}>
          <input
            style={{ ...s.textarea, minHeight: 'unset', marginBottom: 0, padding: '7px 10px', fontSize: 13 }}
            placeholder={loadingPeople ? 'Loading people…' : 'Search by name or department…'}
            value={search}
            onChange={e => setSearch(e.target.value)}
            disabled={loadingPeople}
          />
          <div style={{
            background: '#13151f', border: '1px solid #2a2d40', borderRadius: 7,
            maxHeight: 180, overflowY: 'auto', marginTop: 4,
          }}>
            {filtered.map(emp => (
              <button
                key={emp.employee_code}
                onClick={() => selectPerson(emp)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left',
                  padding: '8px 12px', background: 'transparent', border: 'none',
                  borderBottom: '1px solid #1a1d2e', cursor: 'pointer',
                  color: '#e8e8f0', fontFamily: 'inherit', fontSize: 13,
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#1a1d2e' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ fontWeight: 600 }}>{emp.full_name}</span>
                <span style={{ fontSize: 11, color: '#6b7280', marginLeft: 8 }}>
                  {ROLE_DISPLAY[emp.role] || emp.role}
                  {emp.position ? ` · ${emp.position}` : (emp.department ? ` · ${emp.department}` : '')}
                </span>
              </button>
            ))}
            <button
              onClick={selectExternal}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '8px 12px', background: 'transparent', border: 'none',
                cursor: 'pointer', color: '#9ca3af', fontFamily: 'inherit', fontSize: 13,
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#1a1d2e' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              External (outside company)
            </button>
          </div>
        </div>
      )}

      {/* Share button — always visible, disabled until a person is selected */}
      {!result && (
        <button
          onClick={selected ? handleShare : undefined}
          disabled={!selected || checking || (selected === 'external' && !(externalEmail.includes('@') && externalEmail.includes('.')))}
          style={{
            ...s.btn(selected ? 'primary' : 'secondary'),
            opacity: selected ? 1 : 0.45,
            cursor: selected ? 'pointer' : 'not-allowed',
            marginTop: 8,
          }}
        >
          {checking && <span style={s.spinner} />}
          {checking
            ? 'Sharing…'
            : selected
              ? `Share with ${selected === 'external' ? (externalEmail || 'external recipient') : selected.full_name}`
              : 'Select a person to share'}
        </button>
      )}

      {/* Error */}
      {result?.error && (
        <div style={{ ...s.warningBox, marginTop: 8 }}>Error: {result.error}</div>
      )}

      {/* Clean result */}
      {result && !result.error && !result.flagged && (
        <div style={s.successBox}>
          <strong>✓ Safe to share</strong>
          <div style={{ marginTop: 4, fontSize: 12 }}>
            No restricted content detected for <strong>{recipientLabel}</strong>
            {selected !== 'external' && ` (${roleLabel})`}.
          </div>
        </div>
      )}

      {/* Flagged warning */}
      {result?.flagged && decided !== 'cancelled' && (
        <div style={s.warningBox}>
          <strong>⚠ Heads up before sharing</strong>
          <div style={{ marginTop: 8, lineHeight: 1.6 }}>
            This document contains <strong>{typesLabel || 'sensitive information'}</strong>.<br />
            <strong>{recipientLabel}</strong>{roleLabel ? ` (${roleLabel})` : ''} does not normally
            have access to this type of information.
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: '#fca5a5' }}>
            You can still share — but your decision will be permanently logged with your name and the time.
          </div>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              style={{ ...s.btn('primary'), fontSize: 12 }}
              onClick={() => handleDecide('proceeded')}
              disabled={deciding}
            >
              {deciding && <span style={s.spinner} />}
              Proceed anyway — I accept responsibility
            </button>
            <button
              style={{ ...s.btn('ghost'), fontSize: 12 }}
              onClick={reset}
              disabled={deciding}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── DemoDocCard — one uploaded/pasted document ────────────────────────────────

function DemoDocCard({ doc, userDisplayName }) {
  const types = Object.keys(doc.sensitivity_scan || {})

  const firstVerdict = Object.values(doc.sensitivity_scan || {})
    .map(v => v?.llm_verdict)
    .filter(v => v && v.is_sensitive && v.confidence !== 'low' && v.reason)
    [0]?.reason

  return (
    <div style={s.card}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8f0', marginBottom: 4, wordBreak: 'break-all' }}>
          {doc.filename}
        </div>
        <div style={s.badge(doc.is_sensitive)}>
          {doc.is_sensitive
            ? `⚠ Contains: ${types.map(t => SENSITIVITY_LABELS[t] || t).join(', ')}`
            : '✓ No sensitive content detected'}
        </div>
        {firstVerdict && (
          <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2, lineHeight: 1.4 }}>
            {firstVerdict}
          </div>
        )}
        <div style={{ fontSize: 11, color: '#4b5563', marginTop: 4 }}>
          {new Date(doc.created_at).toLocaleString()}
        </div>
      </div>
      <SharePanel
        docId={doc.id}
        userDisplayName={userDisplayName}
        sensitivityTypes={types}
      />
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function DocumentLibrary({ user }) {
  const [inputMode, setInputMode] = useState('paste') // 'paste' | 'upload'
  const [pasteText, setPasteText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [docs, setDocs] = useState([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [resetting, setResetting] = useState(false)
  const fileRef = useRef()
  const scanDebounceRef = useRef(null)
  const sampleIndexRef = useRef(0)

  const isHR = user && ['hr_staff', 'hr_manager', 'admin'].includes(user.role)
  const displayName = user?.display_name || 'Unknown'

  const loadDocs = useCallback(async () => {
    try {
      const data = await getDemoDocuments()
      setDocs(data.documents || [])
    } catch {
      // ignore
    } finally {
      setLoadingDocs(false)
    }
  }, [])

  useEffect(() => { loadDocs() }, [loadDocs])

  useEffect(() => () => clearTimeout(scanDebounceRef.current), [])

  function handleTrySample() {
    clearTimeout(scanDebounceRef.current)
    setPasteText('')
    const sample = SAMPLE_TEXTS[sampleIndexRef.current % SAMPLE_TEXTS.length]
    sampleIndexRef.current += 1
    setTimeout(() => {
      setPasteText(sample.text)
      scanDebounceRef.current = setTimeout(async () => {
        setScanning(true)
        try {
          await pasteDemoDocument(sample.text, `${sample.label.toLowerCase().replace(/\s+/g, '-')}.txt`)
          setPasteText('')
          await loadDocs()
        } catch {
          // silent
        } finally {
          setScanning(false)
        }
      }, 500)
    }, 50)
  }

  function handlePasteChange(value) {
    setPasteText(value)
    clearTimeout(scanDebounceRef.current)
    if (!value.trim()) return
    scanDebounceRef.current = setTimeout(async () => {
      setScanning(true)
      try {
        await pasteDemoDocument(value, 'pasted-text.txt')
        setPasteText('')
        await loadDocs()
      } catch {
        // silent during auto-scan
      } finally {
        setScanning(false)
      }
    }, 500)
  }

  async function handleFileUpload(file) {
    if (!file) return
    setScanning(true)
    try {
      await uploadDemoDocument(file)
      await loadDocs()
    } catch (err) {
      alert(err.message)
    } finally {
      setScanning(false)
    }
  }

  const onDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFileUpload(file)
  }, [])

  async function handleReset() {
    if (!window.confirm('Delete all demo documents? This cannot be undone.')) return
    setResetting(true)
    try {
      await resetDemoDocuments()
      await loadDocs()
    } catch (err) {
      alert(err.message)
    } finally {
      setResetting(false)
    }
  }

  return (
    <div style={s.root}>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>

      <div style={s.sectionTitle}>Upload & Test</div>

      <div style={s.tabRow}>
        <button style={s.tab(inputMode === 'paste')} onClick={() => setInputMode('paste')}>
          Paste text
        </button>
        <button style={s.tab(inputMode === 'upload')} onClick={() => setInputMode('upload')}>
          Upload file
        </button>
      </div>

      {inputMode === 'paste' && (
        <div>
          <div style={{ position: 'relative' }}>
            <button
              onClick={handleTrySample}
              style={{
                position: 'absolute', top: 6, right: 8, zIndex: 1,
                background: 'none', border: 'none', padding: '2px 4px',
                color: '#6b7280', fontSize: 11, cursor: 'pointer',
              }}
              title={`Next sample: ${SAMPLE_TEXTS[sampleIndexRef.current % SAMPLE_TEXTS.length]?.label}`}
            >
              Try sample ↻
            </button>
            <textarea
              style={s.textarea}
              placeholder={'Paste document content here…\ne.g. "Basic salary: EGP 45,000. National ID: 29901011234567"'}
              value={pasteText}
              onChange={e => handlePasteChange(e.target.value)}
              rows={4}
            />
          </div>
          {scanning && (
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
              <span style={s.spinner} />Scanning…
            </div>
          )}
        </div>
      )}

      {inputMode === 'upload' && (
        <div
          style={{ ...s.dropZone, ...(dragOver ? s.dropZoneActive : {}) }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.doc,.txt"
            style={{ display: 'none' }}
            onChange={e => handleFileUpload(e.target.files[0])}
          />
          {scanning ? (
            <div><span style={s.spinner} />Scanning content…</div>
          ) : (
            <div>
              <div style={{ fontSize: 28, marginBottom: 8 }}>📄</div>
              <div style={{ fontSize: 13, color: '#9ca3af' }}>
                Drop a PDF, DOCX, or TXT file here, or click to browse
              </div>
            </div>
          )}
        </div>
      )}

      {/* Scanned document cards */}
      {loadingDocs ? (
        <div style={{ fontSize: 12, color: '#4b5563', marginTop: 8 }}>Loading…</div>
      ) : docs.length === 0 ? (
        <div style={{ fontSize: 12, color: '#4b5563', marginTop: 8 }}>
          No documents yet — paste or upload something above.
        </div>
      ) : (
        <div style={{ marginTop: 12 }}>
          {docs.map(doc => (
            <DemoDocCard key={doc.id} doc={doc} userDisplayName={displayName} />
          ))}
        </div>
      )}

      {/* Reset — HR/admin only */}
      {isHR && docs.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #1a1d2e' }}>
          <button
            style={{ ...s.btn('ghost'), fontSize: 11 }}
            onClick={handleReset}
            disabled={resetting}
          >
            {resetting ? 'Clearing…' : 'Reset demo — clear all documents'}
          </button>
        </div>
      )}
    </div>
  )
}
