import { useMemo, useState } from 'react'
import { api } from '../api'

const SCENARIOS = [
  { id: 'fiber_cut', label: 'Fiber cut', types: ['hub'], hint: 'A hub uplink is cut. The hub and everything behind it goes dark; one tower fails over to its backup path.' },
  { id: 'tower_power_failure', label: 'Tower power failure', types: ['tower'], hint: 'A tower loses power and its cabinets stop responding.' },
  { id: 'silent_hub_failure', label: 'Silent hub failure', types: ['hub'], hint: 'The hub sends no alert of its own. Only the nodes behind it do, so the root cause has to be inferred.' },
  { id: 'latency_spike', label: 'Latency spike', types: ['tower', 'hub'], hint: 'Repeated latency and packet-loss alerts from one node, many of them duplicates.' },
  { id: 'flapping_link', label: 'Flapping link', types: ['tower'], hint: 'A link goes down and up again several times.' },
  { id: 'cabinet_failure', label: 'Cabinet failure', types: ['cabinet'], hint: 'One street cabinet goes offline.' },
  { id: 'double_incident', label: 'Two faults at once', types: [], hint: 'Two unrelated failures in different parts of the network. They must stay separate incidents.' },
]

export default function SimPanel({ nodes, incidents, onReset }) {
  const [open, setOpen] = useState(() => window.innerWidth > 820) // collapsed on phones so the map stays visible
  const [scenario, setScenario] = useState('fiber_cut')
  const [target, setTarget] = useState('')
  const [speed, setSpeed] = useState('1')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const current = SCENARIOS.find((s) => s.id === scenario)
  const targets = useMemo(
    () => nodes.filter((n) => current.types.includes(n.type)).sort((a, b) => a.name.localeCompare(b.name)),
    [nodes, current]
  )
  const active = incidents.filter((i) => i.status !== 'resolved')

  const pick = (id) => {
    setScenario(id)
    setTarget('')
    setMsg('')
  }

  const run = async () => {
    setBusy(true)
    setMsg('')
    try {
      const r = await api.simulate({ scenario, target: target || null, speed: Number(speed) })
      setMsg(`Sending ${r.events} alerts over about ${r.duration_seconds}s.`)
    } catch (e) {
      setMsg(e.message)
    } finally {
      setBusy(false)
    }
  }

  const restoreAll = async () => {
    setBusy(true)
    try {
      const rs = await Promise.all(active.map((i) => api.restore({ incident_id: i.id })))
      const n = rs.reduce((a, r) => a + r.restoring, 0)
      setMsg(n ? `Restoring ${n} nodes. Incidents resolve after the stability hold.` : 'Nothing to restore.')
    } catch (e) {
      setMsg(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="sim" aria-label="Fault simulator">
      <button className="sim-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>Simulate a fault</span>
        <span className="sim-caret" aria-hidden="true">{open ? '–' : '+'}</span>
      </button>
      {open && (
        <div className="sim-body">
          <div className="sim-list" role="radiogroup" aria-label="Scenario">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                role="radio"
                aria-checked={scenario === s.id}
                className={`sim-opt ${scenario === s.id ? 'is-on' : ''}`}
                onClick={() => pick(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
          <p className="sim-hint">{current.hint}</p>
          <div className="sim-fields">
            <label>
              Location
              <select value={target} onChange={(e) => setTarget(e.target.value)} disabled={!current.types.length}>
                <option value="">{current.types.length ? 'Random' : 'Chosen for you'}</option>
                {targets.map((n) => (
                  <option key={n.id} value={n.id}>{n.name}</option>
                ))}
              </select>
            </label>
            <label>
              Speed
              <select value={speed} onChange={(e) => setSpeed(e.target.value)}>
                <option value="1">Normal</option>
                <option value="3">3x faster</option>
                <option value="0.5">Slow</option>
              </select>
            </label>
          </div>
          <div className="sim-actions">
            <button className="btn primary" onClick={run} disabled={busy}>Run scenario</button>
            <button className="btn" onClick={restoreAll} disabled={busy || !active.length}>Restore network</button>
            <button className="btn quiet" onClick={onReset}>Reset demo</button>
          </div>
          {msg && <p className="sim-msg" role="status">{msg}</p>}
        </div>
      )}
    </section>
  )
}
