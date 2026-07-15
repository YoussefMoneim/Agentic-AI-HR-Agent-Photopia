const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function authHeaders() {
  const token = localStorage.getItem('hr_agent_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Onboarding steps 4-5 (handbook / leave-policy upload) — see
// backend/api/main.py::onboarding_upload. Kept alongside this owned
// directory rather than in the shared api.js, matching the file-ownership
// convention agreed for this sprint.
export async function uploadOnboardingDocument(sessionId, file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_URL}/api/onboarding/${sessionId}/upload`, {
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
