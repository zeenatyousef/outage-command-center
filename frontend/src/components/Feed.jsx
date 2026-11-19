import { RESULT_LABEL, TYPE_LABEL, clock } from '../fmt'

export default function Feed({ items, onOpen }) {
  if (!items.length) {
    return (
      <div className="empty">
        <strong>No alerts yet</strong>
        <p>Every raw alert appears here the moment it arrives. Repeats are marked as collapsed, so you can see the noise the correlation removes.</p>
      </div>
    )
  }
  return (
    <ul className="feed">
      {items.map((a, idx) => (
        <li key={`${a.ts}-${idx}-${a.node_id}`} className={`feed-row res-${a.result}`}>
          <span className="feed-time">{clock(a.ts)}</span>
          <span className="feed-what">
            <span className="feed-type">{TYPE_LABEL[a.type] || a.type}</span>
            <span className="feed-node">{a.node_name}</span>
          </span>
          {a.incident_id ? (
            <button className="feed-res" onClick={() => onOpen(a.incident_id)} title="Open the incident this alert belongs to">
              {RESULT_LABEL[a.result] || a.result}
            </button>
          ) : (
            <span className="feed-res">{RESULT_LABEL[a.result] || a.result}</span>
          )}
        </li>
      ))}
    </ul>
  )
}
