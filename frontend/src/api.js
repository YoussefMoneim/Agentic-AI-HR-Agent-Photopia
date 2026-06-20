const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function sendChat(message, sessionId, demoRole) {
  const body = { message }
  if (sessionId) body.session_id = sessionId
  if (demoRole) body.demo_role = demoRole
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error ${res.status}: ${text}`)
  }
  return res.json()
}

export async function fetchAuditLog(limit = 15) {
  const res = await fetch(`${API_URL}/api/audit-log?limit=${limit}`)
  if (!res.ok) throw new Error(`Audit log ${res.status}`)
  return res.json()
}

export async function fetchPendingCount() {
  const res = await fetch(`${API_URL}/api/leave/pending-count`)
  if (!res.ok) throw new Error(`Pending count ${res.status}`)
  return res.json()
}

export function documentUrl(docId) {
  return `${API_URL}/documents/${docId}`
}
