import { useCallback, useEffect, useState } from 'react'
import { getKnowledgeDocuments, getSharePointStatus, triggerSharePointSync } from '../api.js'

const s = {
  root: {
    height: '100%', overflowY: 'auto', padding: '20px 16px',
    background: '#0f1117', color: '#e8e8f0', fontFamily: 'inherit',
  },
  sectionTitle: {
    fontSize: 11, letterSpacing: 2, textTransform: 'uppercase',
    color: '#4b5563', marginBottom: 12, marginTop: 4,
  },
  statusCard: {
    background: '#13151f', border: '1px solid #1a1d2e', borderRadius: 10,
    padding: '16px', marginBottom: 20,
  },
  statusRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    fontSize: 13, padding: '6px 0',
  },
  statusLabel: { color: '#6b7280' },
  statusValue: { color: '#e8e8f0', fontWeight: 600 },
  badge: (ok) => ({
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '3px 10px', borderRadius: 99, fontSize: 11, fontWeight: 700,
    background: ok ? '#0a2a0a' : '#2d0f0f',
    color: ok ? '#86efac' : '#fca5a5',
    border: `1px solid ${ok ? '#166534' : '#7f1d1d'}`,
  }),
  btn: {
    padding: '8px 16px', borderRadius: 7, fontSize: 13, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer',
    background: '#4f46e5', color: '#fff', border: 'none',
    marginTop: 10, width: '100%',
  },
  btnDisabled: { opacity: 0.6, cursor: 'default' },
  card: {
    background: '#13151f', border: '1px solid #1a1d2e', borderRadius: 10,
    padding: '12px 14px', marginBottom: 8,
  },
  docName: { fontSize: 13, fontWeight: 600, color: '#e8e8f0', marginBottom: 4 },
  docMeta: { fontSize: 12, color: '#6b7280' },
  errorBox: {
    background: '#2d0f0f', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '10px 14px', marginTop: 10, fontSize: 12, color: '#fca5a5',
  },
  empty: { fontSize: 13, color: '#4b5563', padding: '20px 0', textAlign: 'center' },
  spinner: {
    display: 'inline-block', width: 14, height: 14,
    border: '2px solid rgba(255,255,255,0.3)', borderTop: '2px solid #fff',
    borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    marginRight: 8, verticalAlign: 'middle',
  },
}

function formatDateTime(str) {
  if (!str) return 'Never'
  try {
    return new Date(str).toLocaleString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch { return str }
}

export default function KnowledgeSyncPanel() {
  const [docs, setDocs] = useState([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [status, setStatus] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState(null)

  const loadAll = useCallback(async () => {
    try {
      const data = await getKnowledgeDocuments()
      setDocs(data.documents || [])
    } catch {
      // ignore — panel still shows sync status even if documents fail to load
    } finally {
      setLoadingDocs(false)
    }
    try {
      const data = await getSharePointStatus()
      setStatus(data)
    } catch {
      // ignore
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleSyncNow() {
    setSyncing(true)
    setError(null)
    try {
      await triggerSharePointSync()
      await loadAll()
    } catch (err) {
      setError(err.message)
    } finally {
      setSyncing(false)
    }
  }

  const disabled = status && status.status === 'disabled'

  return (
    <div style={s.root}>
      <div style={s.sectionTitle}>SharePoint Sync</div>

      <div style={s.statusCard}>
        {loadingStatus ? (
          <div style={s.statusRow}><span style={s.statusLabel}>Loading status…</span></div>
        ) : disabled ? (
          <div style={s.statusRow}>
            <span style={s.statusLabel}>Connector</span>
            <span style={s.badge(false)}>Not configured</span>
          </div>
        ) : (
          <>
            <div style={s.statusRow}>
              <span style={s.statusLabel}>Last synced</span>
              <span style={s.statusValue}>
                {formatDateTime(status?.sync_state?.last_synced_at)}
              </span>
            </div>
            <div style={s.statusRow}>
              <span style={s.statusLabel}>Site</span>
              <span style={s.statusValue}>{status?.sync_state?.site_url || '—'}</span>
            </div>
            <div style={s.statusRow}>
              <span style={s.statusLabel}>Status</span>
              <span style={s.badge(!status?.sync_state?.last_error)}>
                {status?.sync_state?.last_error ? 'Last sync failed' : 'Healthy'}
              </span>
            </div>
          </>
        )}

        <button
          onClick={handleSyncNow}
          disabled={syncing || disabled}
          style={{ ...s.btn, ...(syncing || disabled ? s.btnDisabled : {}) }}
        >
          {syncing && <span style={s.spinner} />}
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>

        {error && <div style={s.errorBox}>{error}</div>}
      </div>

      <div style={s.sectionTitle}>Knowledge Base Documents ({docs.length})</div>

      {loadingDocs ? (
        <div style={s.empty}>Loading documents…</div>
      ) : docs.length === 0 ? (
        <div style={s.empty}>No documents ingested yet.</div>
      ) : (
        docs.map((doc) => (
          <div key={doc.document_id} style={s.card}>
            <div style={s.docName}>{doc.document_id}</div>
            <div style={s.docMeta}>
              {doc.chunk_count} chunks · {doc.access_level} · ingested {formatDateTime(doc.ingested_at)}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
