import { documentUrl } from '../api.js'

const DOCUMENT_TYPE_LABELS = {
  salary_certificate: 'Salary Certificate',
  twimc_letter: 'Employment Letter',
  experience_certificate: 'Experience Certificate',
}

export default function DocumentCard({ doc }) {
  const label = DOCUMENT_TYPE_LABELS[doc.type] || 'Document'

  return (
    <a
      href={documentUrl(doc.id)}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '10px',
        marginTop: '10px',
        padding: '10px 16px',
        background: '#1e2235',
        border: '1px solid #2d3561',
        borderRadius: '10px',
        color: '#a5b4fc',
        textDecoration: 'none',
        fontSize: '13px',
        fontWeight: 500,
        transition: 'background 0.15s',
      }}
      onMouseOver={e => e.currentTarget.style.background = '#252b42'}
      onMouseOut={e => e.currentTarget.style.background = '#1e2235'}
    >
      <PdfIcon />
      <span>
        <span style={{ display: 'block', color: '#e8e8f0', fontWeight: 600 }}>
          {label}
        </span>
        <span style={{ color: '#888' }}>
          {doc.employee_name || 'Employee'} · Click to open PDF
        </span>
      </span>
    </a>
  )
}

function PdfIcon() {
  return (
    <svg width="28" height="32" viewBox="0 0 28 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="28" height="32" rx="4" fill="#2d3561"/>
      <text x="4" y="22" fill="#a5b4fc" fontSize="10" fontWeight="bold" fontFamily="monospace">PDF</text>
    </svg>
  )
}
