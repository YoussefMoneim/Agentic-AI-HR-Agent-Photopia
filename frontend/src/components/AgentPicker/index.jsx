// Single-option dropdown for Week 1 — a seam, not a real picker yet.
// No agent_configs table exists in main yet (Youssef's Week 1 foundation),
// so there's exactly one agent to show. Swapping this to a real list later
// only means changing AGENTS below to a fetched list — nothing that mounts
// this component needs to change.
const AGENTS = [{ id: 'fotopia-hr-agent', name: 'Fotopia HR Agent' }]

export default function AgentPicker() {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '8px',
        padding: '6px 12px',
        background: '#13151f',
        border: '1px solid #252b42',
        borderRadius: '10px',
        color: '#e8e8f0',
        fontSize: '13px',
        fontWeight: 500,
        width: 'fit-content',
      }}
    >
      <span style={{
        width: 20, height: 20, borderRadius: '50%', background: '#2d3561',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: '11px', fontWeight: 700, color: '#a5b4fc', flexShrink: 0,
      }}>
        F
      </span>
      {AGENTS[0].name}
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth="2">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </div>
  )
}
