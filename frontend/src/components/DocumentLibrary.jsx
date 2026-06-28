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

const DOC_TYPE_LABELS = {
  salary_certificate: 'Salary Certificate',
  twimc_letter: 'TWIMC Letter',
  experience_certificate: 'Experience Certificate',
}

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
    border: 'none', cursor: 'pointer', fontFamily: 'inherit',
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
  warningBox: {
    background: '#2d0f0f', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '12px 14px', marginTop: 10, fontSize: 13, color: '#fca5a5',
    lineHeight: 1.5,
  },
  successBox: {
    background: '#0a2a0a', border: '1px solid #166534', borderRadius: 8,
    padding: '12px 14px', marginTop: 10, fontSize: 13, color: '#86efac',
    lineHeight: 1.5,
  },
  select: {
    background: '#13151f', border: '1px solid #2a2d40', borderRadius: 7,
    color: '#e8e8f0', padding: '7px 10px', fontSize: 13, fontFamily: 'inherit',
    cursor: 'pointer', outline: 'none', marginRight: 8,
  },
  spinner: {
    display: 'inline-block', width: 14, height: 14,
    border: '2px solid #2a2d40', borderTop: '2px solid #6c7aff',
    borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    marginRight: 6, verticalAlign: 'middle',
  },
}

// ── SharePanel — inline share flow for one document card ──────────────────────

const EXTERNAL_VALUE = '__external__'

function SharePanel({ docId, userDisplayName }) {
  const [employees, setEmployees] = useState([])
  const [loadingPeople, setLoadingPeople] = useState(true)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null) // null | {employee_code, full_name, role} | 'external'
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState(null)   // null | {flagged, ...}
  const [decided, setDecided] = useState(null) // null | 'proceeded' | 'cancelled'
  const [deciding, setDeciding] = useState(false)

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
  }

  async function handleCheck() {
    if (!selected) return
    setChecking(true)
    setResult(null)
    setDecided(null)
    try {
      const isExternal = selected === 'external'
      const data = await checkDocumentShare(docId, {
        recipientEmployeeCode: isExternal ? null : selected.employee_code,
        recipientRole: isExternal ? null : selected.role,
        recipientName: isExternal ? null : selected.full_name,
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
      setDecided(decision)
    } finally {
      setDeciding(false)
    }
  }

  function reset() {
    setSelected(null)
    setResult(null)
    setDecided(null)
  }

  if (decided) {
    const recipientLabel = selected === 'external'
      ? 'External recipient'
      : (selected?.full_name || 'recipient')
    return (
      <div style={{ marginTop: 8 }}>
        {decided === 'proceeded' ? (
          <div style={s.successBox}>
            Shared with <strong>{recipientLabel}</strong> — decision logged ✓
            <div style={{ fontSize: 11, color: '#4ade80', marginTop: 4 }}>
              Recorded as: <strong>{userDisplayName}</strong>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 8 }}>
            Sharing cancelled — no action taken.
          </div>
        )}
        <button style={{ ...s.btn('ghost'), marginTop: 8, fontSize: 11 }} onClick={reset}>
          Share again
        </button>
      </div>
    )
  }

  const selectedLabel = selected === 'external'
    ? 'External (outside company)'
    : selected
      ? `${selected.full_name} · ${ROLE_DISPLAY[selected.role] || selected.role}`
      : null

  return (
    <div style={{ marginTop: 10 }}>
      {/* People picker */}
      <div style={{ marginBottom: 8 }}>
        {selected ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
        ) : (
          <div style={{ position: 'relative' }}>
            <input
              style={{ ...s.textarea, minHeight: 'unset', marginBottom: 0, padding: '7px 10px', fontSize: 13 }}
              placeholder={loadingPeople ? 'Loading people…' : 'Search by name or department…'}
              value={search}
              onChange={e => setSearch(e.target.value)}
              disabled={loadingPeople}
            />
            {(search.trim() || !selected) && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                background: '#13151f', border: '1px solid #2a2d40', borderRadius: 7,
                maxHeight: 180, overflowY: 'auto', marginTop: 2,
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
            )}
          </div>
        )}
      </div>

      {selected && (
        <button style={s.btn()} onClick={handleCheck} disabled={checking}>
          {checking && <span style={s.spinner} />}
          {checking ? 'Checking…' : 'Check & Share'}
        </button>
      )}

      {result?.error && (
        <div style={{ ...s.warningBox, marginTop: 8 }}>Error: {result.error}</div>
      )}

      {result && !result.error && !result.flagged && (
        <div style={s.successBox}>
          Ready to share — no restrictions detected ✓
        </div>
      )}

      {result?.flagged && (
        <div style={s.warningBox}>
          <strong>⚠ Sensitivity flag</strong>
          <div style={{ marginTop: 6, lineHeight: 1.5 }}>{result.reason}</div>
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <button
              style={{ ...s.btn('primary'), fontSize: 12 }}
              onClick={() => handleDecide('proceeded')}
              disabled={deciding}
            >
              Proceed anyway — log my decision
            </button>
            <button
              style={{ ...s.btn('ghost'), fontSize: 12 }}
              onClick={() => handleDecide('cancelled')}
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
  const [expanded, setExpanded] = useState(false)
  const types = Object.keys(doc.sensitivity_scan || {})

  return (
    <div style={s.card}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8f0', marginBottom: 4, wordBreak: 'break-all' }}>
            {doc.filename}
          </div>
          <div style={s.badge(doc.is_sensitive)}>
            {doc.is_sensitive
              ? `Sensitive: ${types.join(', ')}`
              : 'Clean — no sensitive content'}
          </div>
          {doc.is_sensitive && (() => {
            const firstVerdict = Object.values(doc.sensitivity_scan || {})
              .map(v => v?.llm_verdict?.reason)
              .filter(Boolean)[0]
            return firstVerdict
              ? <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2, lineHeight: 1.4 }}>{firstVerdict}</div>
              : null
          })()}
          <div style={{ fontSize: 11, color: '#4b5563', marginTop: 4 }}>
            {new Date(doc.created_at).toLocaleString()}
          </div>
        </div>
        <button
          style={{ ...s.btn('ghost'), fontSize: 11, whiteSpace: 'nowrap', flexShrink: 0 }}
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? 'Hide share' : 'Share…'}
        </button>
      </div>
      {expanded && <SharePanel docId={doc.id} userDisplayName={userDisplayName} />}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function DocumentLibrary({ user }) {
  const [inputMode, setInputMode] = useState('paste') // 'paste' | 'upload'
  const [pasteText, setPasteText] = useState('')
  const [pasteFilename, setPasteFilename] = useState('demo-document.txt')
  const [dragOver, setDragOver] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [docs, setDocs] = useState([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [resetting, setResetting] = useState(false)
  const fileRef = useRef()

  const isHR = user && ['hr_staff', 'hr_manager', 'admin'].includes(user.role)
  const displayName = user?.display_name || 'Unknown'

  const loadDocs = useCallback(async () => {
    try {
      const data = await getDemoDocuments()
      setDocs(data.documents || [])
    } catch {
      // ignore — user might not be logged in yet
    } finally {
      setLoadingDocs(false)
    }
  }, [])

  useEffect(() => { loadDocs() }, [loadDocs])

  async function handlePaste() {
    if (!pasteText.trim()) return
    setScanning(true)
    try {
      await pasteDemoDocument(pasteText, pasteFilename || 'pasted-text.txt')
      setPasteText('')
      await loadDocs()
    } catch (err) {
      alert(err.message)
    } finally {
      setScanning(false)
    }
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

      {/* Section A: Upload & Test */}
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
          <textarea
            style={s.textarea}
            placeholder={'Paste document content here…\ne.g. "Basic salary: EGP 45,000. National ID: 29901011234567"'}
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
            rows={4}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
            <input
              style={{ ...s.textarea, minHeight: 'unset', marginBottom: 0, flex: 1, padding: '7px 10px', fontSize: 12 }}
              placeholder="Document name (optional)"
              value={pasteFilename}
              onChange={e => setPasteFilename(e.target.value)}
            />
            <button
              style={{ ...s.btn(), whiteSpace: 'nowrap' }}
              onClick={handlePaste}
              disabled={scanning || !pasteText.trim()}
            >
              {scanning && <span style={s.spinner} />}
              {scanning ? 'Scanning…' : 'Scan content'}
            </button>
          </div>
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

      {/* Reset button — HR/admin only */}
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
