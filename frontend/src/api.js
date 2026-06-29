const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function getToken() {
  return localStorage.getItem('hr_agent_token')
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function login(email, password) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Login failed (${res.status})`)
  }
  const data = await res.json()
  localStorage.setItem('hr_agent_token', data.access_token)
  return data  // { access_token, token_type, role, display_name, employee_code }
}

export function logout() {
  localStorage.removeItem('hr_agent_token')
}

export function getStoredUser() {
  const token = getToken()
  if (!token) return null
  try {
    // Decode the JWT payload (base64url, middle segment)
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    // Check expiry
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      localStorage.removeItem('hr_agent_token')
      return null
    }
    return {
      role: payload.role,
      display_name: payload.display_name,
      employee_code: payload.employee_code,
    }
  } catch {
    localStorage.removeItem('hr_agent_token')
    return null
  }
}

export async function sendChat(message, sessionId, demoRole) {
  const body = { message }
  if (sessionId) body.session_id = sessionId
  // demo_role is only used as fallback when no JWT is present (DEBUG mode)
  if (demoRole && !getToken()) body.demo_role = demoRole
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (res.status === 401) {
    localStorage.removeItem('hr_agent_token')
    window.location.reload()
    throw new Error('Session expired. Please log in again.')
  }
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

export async function fetchPendingApprovals() {
  const res = await fetch(`${API_URL}/api/leave/pending-approvals-queue`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Pending approvals ${res.status}`)
  return res.json()
}

export async function approveLeaveRequest(requestId, comment, overrideReason) {
  const res = await fetch(`${API_URL}/api/leave/${requestId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ comment: comment || null, override_reason: overrideReason || null }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Approve failed (${res.status})`)
  }
  return res.json()
}

export async function checkLeaveConstraints(requestId) {
  const res = await fetch(`${API_URL}/api/leave/${requestId}/check-constraints`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Constraint check failed (${res.status})`)
  return res.json()
}

export async function rejectLeaveRequest(requestId, comment) {
  const res = await fetch(`${API_URL}/api/leave/${requestId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ comment }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Reject failed (${res.status})`)
  }
  return res.json()
}

// ── Document Library ───────────────────────────────────────────────────────────

export async function uploadDemoDocument(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_URL}/api/documents/upload-demo`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: form,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Upload failed (${res.status})`)
  }
  return res.json()
}

export async function pasteDemoDocument(content, filename = 'pasted-text.txt') {
  const res = await fetch(`${API_URL}/api/documents/paste-demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content, filename }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Paste failed (${res.status})`)
  }
  return res.json()
}

export async function getDemoDocuments() {
  const res = await fetch(`${API_URL}/api/documents/demo`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Demo documents ${res.status}`)
  return res.json()
}

export async function listEmployees() {
  const res = await fetch(`${API_URL}/api/employees`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Employee list ${res.status}`)
  return res.json()
}

export async function checkDocumentShare(docId, { recipientRole, recipientEmployeeCode, recipientName } = {}) {
  const res = await fetch(`${API_URL}/api/documents/demo/${docId}/check-share`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      recipient_role: recipientRole ?? null,
      recipient_employee_code: recipientEmployeeCode ?? null,
      recipient_name: recipientName ?? null,
    }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Share check failed (${res.status})`)
  }
  return res.json()
}

export async function recordShareDecision(eventId, decision) {
  const res = await fetch(`${API_URL}/api/appropriateness/${eventId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ decision }),
  })
  if (!res.ok) throw new Error(`Decision record failed (${res.status})`)
  return res.json()
}

export async function resetDemoDocuments() {
  const res = await fetch(`${API_URL}/api/documents/demo/reset`, {
    method: 'DELETE',
    headers: { ...authHeaders() },
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Reset failed (${res.status})`)
  }
  return res.json()
}

export async function getPendingCancellations() {
  const res = await fetch(`${API_URL}/api/leave/pending-cancellations`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Pending cancellations ${res.status}`)
  return res.json()
}

export async function approveLeaveCancellation(requestId, consumedDays) {
  const res = await fetch(`${API_URL}/api/leave/${requestId}/approve-cancellation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ consumed_days: consumedDays ?? null }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Approve cancellation failed (${res.status})`)
  }
  return res.json()
}

export async function getRecentDocuments() {
  const res = await fetch(`${API_URL}/api/documents/recent`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Recent documents ${res.status}`)
  return res.json()
}

export async function getLeaveCalendar(year, month, department = null) {
  const params = new URLSearchParams({ year, month })
  if (department) params.append('department', department)
  const res = await fetch(`${API_URL}/api/calendar/leave?${params}`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(`Calendar fetch failed (${res.status})`)
  return res.json()
}
