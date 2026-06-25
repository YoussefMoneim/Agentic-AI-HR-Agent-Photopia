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

export async function approveLeaveRequest(requestId, comment) {
  const res = await fetch(`${API_URL}/api/leave/${requestId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ comment: comment || null }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Approve failed (${res.status})`)
  }
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
