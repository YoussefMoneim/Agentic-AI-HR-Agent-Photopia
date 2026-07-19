import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import DocumentCard from './DocumentCard.jsx'

const MARKDOWN_COMPONENTS = {
  p: ({ children }) => (
    <p style={{ margin: '0 0 8px 0', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>{children}</p>
  ),
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '8px 0' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '13px', lineHeight: '1.4' }}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr>{children}</tr>,
  th: ({ children }) => (
    <th style={{
      padding: '6px 12px',
      borderBottom: '1px solid #2d3561',
      borderRight: '1px solid #1e2440',
      background: '#1a1d2e',
      color: '#a5b4fc',
      fontWeight: 600,
      textAlign: 'left',
      whiteSpace: 'nowrap',
    }}>{children}</th>
  ),
  td: ({ children }) => (
    <td style={{
      padding: '5px 12px',
      borderBottom: '1px solid #1a1d2e',
      borderRight: '1px solid #1a1d2e',
      color: '#c8c8d8',
      verticalAlign: 'top',
    }}>{children}</td>
  ),
  code: ({ inline, children }) => inline ? (
    <code style={{
      background: '#1a1d2e', color: '#a5b4fc',
      padding: '1px 5px', borderRadius: '4px',
      fontSize: '12px', fontFamily: 'monospace',
    }}>{children}</code>
  ) : (
    <pre style={{
      background: '#1a1d2e', color: '#c8c8d8',
      padding: '10px 14px', borderRadius: '8px',
      overflowX: 'auto', fontSize: '12px',
      fontFamily: 'monospace', margin: '8px 0', whiteSpace: 'pre',
    }}>
      <code>{children}</code>
    </pre>
  ),
  ul: ({ children }) => <ul style={{ paddingLeft: '20px', margin: '4px 0 8px' }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ paddingLeft: '20px', margin: '4px 0 8px' }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: '2px 0', color: '#c8c8d8', lineHeight: '1.5' }}>{children}</li>,
  strong: ({ children }) => <strong style={{ color: '#e8e8f0', fontWeight: 600 }}>{children}</strong>,
  em: ({ children }) => <em style={{ color: '#a5b4fc' }}>{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
      style={{ color: '#818cf8', textDecoration: 'underline' }}>{children}</a>
  ),
  h1: ({ children }) => <h1 style={{ fontSize: '16px', fontWeight: 700, color: '#e8e8f0', margin: '12px 0 6px' }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: '15px', fontWeight: 600, color: '#e8e8f0', margin: '10px 0 4px' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#a5b4fc', margin: '8px 0 4px' }}>{children}</h3>,
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid #1a1d2e', margin: '10px 0' }} />,
}

// User bubble background by role
const USER_STYLE = {
  employee:   { bg: '#1a2f4e', border: '#284070' },
  hr_manager: { bg: '#28154a', border: '#3e1e6e' },
}

function PaperclipIconTiny() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
      <path d="M21.44 11.05l-9.19 9.19a5 5 0 01-7.07-7.07l9.19-9.19a3.5 3.5 0 015 5l-9.2 9.19a1.5 1.5 0 01-2.12-2.12l8.49-8.48" />
    </svg>
  )
}

export default function MessageBubble({ message, demoRole }) {
  const isUser = message.role === 'user'
  const userStyle = USER_STYLE[demoRole] || USER_STYLE.hr_manager

  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: '12px',
      alignItems: 'flex-start',
    }}>
      {!isUser && (
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: '#2d3561', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '13px', fontWeight: 700, color: '#a5b4fc',
          marginRight: '10px', marginTop: '2px',
        }}>
          F
        </div>
      )}

      <div style={{ maxWidth: '72%' }}>
        <div style={{
          padding: '12px 16px',
          borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
          background: isUser ? userStyle.bg : '#1a1d2e',
          border: `1px solid ${isUser ? userStyle.border : '#252b42'}`,
          fontSize: '14px',
          lineHeight: '1.6',
          color: '#e8e8f0',
          wordBreak: 'break-word',
        }}>
          {isUser ? (
            <>
              {message.attachedFileNames?.length > 0 && (
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: '3px',
                  marginBottom: message.text ? '8px' : 0,
                }}>
                  {message.attachedFileNames.map((name, i) => (
                    <div key={`${name}-${i}`} style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      fontSize: '12px', color: '#c8c8d8', opacity: 0.85,
                    }}>
                      <PaperclipIconTiny />
                      {name}
                    </div>
                  ))}
                </div>
              )}
              {message.text && <span style={{ whiteSpace: 'pre-wrap' }}>{message.text}</span>}
            </>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
              {message.text}
            </ReactMarkdown>
          )}
        </div>

        {message.documents && message.documents.length > 0 && (
          <div style={{ marginTop: '4px' }}>
            {message.documents.map(doc => (
              <DocumentCard key={doc.id} doc={doc} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
