import { useState } from 'react'
import { KIND_LABEL, STATUS_LABEL, ago, num } from '../fmt'

export default function IncidentList({ incidents, now, onOpen }) {
  const [showResolved, setShowResolved] = useState(true)
  const visible = incidents.filter((i) => showResolved || i.status !== 'resolved')

  return (
    <div className="list">
      <div className="list-tools">
        <label className="check">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
          Show resolved
        </label>
      </div>
      {visible.length === 0 ? (
        <div className="empty">
          <strong>No incidents</strong>
          <p>Run a scenario from the panel on the map to watch alerts turn into one incident.</p>
        </div>
      ) : (
        <ul className="rows">
          {visible.map((i) => (
            <li key={i.id}>
              <button className={`row sev-${i.severity} st-${i.status}`} onClick={() => onOpen(i.id)}>
                <span className="row-bar" aria-hidden="true" />
                <span className="row-main">
                  <span className="row-title">{i.title}</span>
                  <span className="row-impact">
                    {i.customers_offline > 0 || i.customers_degraded > 0 ? (
                      <>
                        {i.customers_offline > 0 && <span className="t-down">{num(i.customers_offline)} offline</span>}
                        {i.customers_degraded > 0 && <span className="t-degraded">{num(i.customers_degraded)} degraded</span>}
                      </>
                    ) : (
                      <span>{i.peak_offline ? `Peak ${num(i.peak_offline)} offline` : 'No customers affected now'}</span>
                    )}
                  </span>
                  <span className="row-meta">
                    <span className={`chip st-${i.status}`}>{STATUS_LABEL[i.status]}</span>
                    {i.kind !== 'outage' && <span className="chip">{KIND_LABEL[i.kind]}</span>}
                    {i.inferred ? <span className="chip chip-inferred">Root cause inferred</span> : null}
                    <span>{num(i.raw_alert_count)} {i.raw_alert_count === 1 ? 'alert' : 'alerts'}</span>
                    <span>{ago(now, i.started_ts)}</span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
