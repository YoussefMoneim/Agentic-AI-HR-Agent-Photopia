import { useRef, useState } from 'react'
import { uploadOnboardingDocument } from './uploadApi.js'

// Shown next to the composer whenever the backend reports awaiting_upload —
// the attach affordance for onboarding steps 4/5 (handbook / leave policy).
// Still "talking to the agent": the resulting reply is appended to the same
// chat thread, just triggered by a file picker instead of typed text.
export default function OnboardingUploadButton({ sessionId, disabled, onUploaded, onError }) {
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef(null)

  async function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file next time
    if (!file) return
    setUploading(true)
    try {
      const data = await uploadOnboardingDocument(sessionId, file)
      onUploaded(data)
    } catch (err) {
      onError(err)
    } finally {
      setUploading(false)
    }
  }

  const isDisabled = disabled || uploading

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.doc,.txt"
        style={{ display: 'none' }}
        onChange={handleFile}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={isDisabled}
        title="Attach a document"
        style={{
          width: 36, height: 36,
          borderRadius: '10px',
          background: isDisabled ? '#1a1d2e' : '#13151f',
          border: '1px solid #252b42',
          color: isDisabled ? '#444' : '#a5b4fc',
          cursor: isDisabled ? 'default' : 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <PaperclipIcon spinning={uploading} />
      </button>
    </>
  )
}

function PaperclipIcon({ spinning }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      style={spinning ? { animation: 'spin 0.9s linear infinite' } : undefined}
    >
      <path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 015 5l-9.2 9.19a1.5 1.5 0 01-2.12-2.12l8.49-8.48" />
    </svg>
  )
}
