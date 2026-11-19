import { duration, num } from '../fmt'

export default function KpiStrip({ m }) {
  if (!m) return <div className="kpis"><div className="kpi"><div className="kpi-label">Connecting to the backend…</div></div></div>
  const pct = (v) => (m.customers_total ? ((v / m.customers_total) * 100).toFixed(1) : '0.0')
  const incidentBar = m.raw_alerts ? Math.max(1.5, (m.incidents_total / m.raw_alerts) * 100) : 0

  return (
    <div className="kpis">
      <div className="kpi">
        <div className={`kpi-num ${m.customers_offline ? 'is-down' : ''}`}>{num(m.customers_offline)}</div>
        <div className="kpi-label">customers offline</div>
        <div className="kpi-sub">{pct(m.customers_offline)}% of {num(m.customers_total)}</div>
      </div>
      <div className="kpi">
        <div className={`kpi-num ${m.customers_degraded ? 'is-degraded' : ''}`}>{num(m.customers_degraded)}</div>
        <div className="kpi-label">customers degraded</div>
        <div className="kpi-sub">{m.nodes_down} nodes down, {m.nodes_degraded} degraded</div>
      </div>
      <div className="kpi">
        <div className="kpi-num">{m.incidents_active}</div>
        <div className="kpi-label">active incidents</div>
        <div className="kpi-sub">{m.incidents_total} since the last reset</div>
      </div>
      <div className="kpi kpi-noise" title="Raw alerts received compared with incidents after correlation">
        <div className="noise-rows">
          <div className="noise-row">
            <span className="noise-count">{num(m.raw_alerts)}</span>
            <span className="noise-name">raw alerts</span>
            <span className="noise-bar"><i style={{ width: m.raw_alerts ? '100%' : 0 }} /></span>
          </div>
          <div className="noise-row">
            <span className="noise-count">{num(m.incidents_total)}</span>
            <span className="noise-name">incidents</span>
            <span className="noise-bar"><i className="is-incident" style={{ width: `${incidentBar}%` }} /></span>
          </div>
        </div>
        <div className="kpi-sub">
          {m.raw_alerts ? `${m.noise_reduction_pct}% less noise after correlation` : 'Waiting for alerts'}
        </div>
      </div>
      <div className="kpi">
        <div className="kpi-num">{m.mttr_seconds == null ? '–' : duration(m.mttr_seconds)}</div>
        <div className="kpi-label">average time to resolve</div>
        <div className="kpi-sub">resolved incidents only</div>
      </div>
    </div>
  )
}
