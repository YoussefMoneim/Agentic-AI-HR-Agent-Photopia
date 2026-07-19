import { useRef } from 'react'

// Just the file picker — selecting file(s) stages them (onFilesSelected)
// rather than uploading immediately. The actual upload happens when the
// user hits Send, at the same time as any typed text, so they can compose a
// message, attach one or more files (multiple selected at once, or the
// button clicked again to add more), remove any before sending, and send
// everything together — see ChatInterface.jsx's handleSend / stagedFiles.
export default function OnboardingUploadButton({ disabled, onFilesSelected }) {
  const inputRef = useRef(null)

  function handleFile(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = '' // allow re-selecting the same file(s) next time
    if (!files.length) return
    onFilesSelected(files)
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.doc,.txt"
        multiple
        style={{ display: 'none' }}
        onChange={handleFile}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        title="Attach a document"
        style={{
          width: 36, height: 36,
          borderRadius: '10px',
          background: disabled ? '#1a1d2e' : '#13151f',
          border: '1px solid #252b42',
          color: disabled ? '#444' : '#a5b4fc',
          cursor: disabled ? 'default' : 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <PaperclipIcon />
      </button>
    </>
  )
}

function PaperclipIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 015 5l-9.2 9.19a1.5 1.5 0 01-2.12-2.12l8.49-8.48" />
    </svg>
  )
}
