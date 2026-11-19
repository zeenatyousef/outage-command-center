import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { KIND_LABEL, SOURCE_LABEL, STATUS_LABEL, TYPE_LABEL, ago, clock, duration, num } from '../fmt'

export default function IncidentDetail({ id, stamp, config, now, onBack }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState('')
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api.incident(id).then(setD).catch((e) => setError(e.message)), [id])

  useEffect(() => {
    setD(null)
    setError('')
    setEditing(false)
    load()
  }, [id, load])

  // refresh when the live incident summary changes
  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [stamp, load])

  const act = async (fn) => {
    setBusy(true)
    setError('')
    try {
      const r = await fn()
      if (r && r.id) setD(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !d) {
    return (
      <div className="detail">
        <button className="back" onClick={onBack}>All incidents</button>
        <div className="empty"><strong>Could not load this incident</strong><p>{error}</p></div>
      </div>
    )
  }
  if (!d) return <div className="detail"><button className="back" onClick={onBack}>All incidents</button><p className="muted pad">Loading…</p></div>

  const openAlerts = d.alerts.filter((a) => a.state === 'open').length
  const resolved = d.status === 'resolved'
  const end = d.resolved_ts || now
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(d.status_update || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Copy was blocked by the browser. Select the text and copy it manually.')
    }
  }

  return (
    <div className="detail">
      <button className="back" onClick={onBack}>All incidents</button>

      <header className={`d-head sev-${d.severity}`}>
        <h2>{d.title}</h2>
        <div className="chips">
          <span className={`chip st-${d.status}`}>{STATUS_LABEL[d.status]}</span>
          <span className={`chip sev-chip sev-${d.severity}`}>{d.severity}</span>
          <span className="chip">{KIND_LABEL[d.kind]}</span>
          {d.inferred ? <span className="chip chip-inferred" title="No alert came from the root node itself; it was inferred from the nodes behind it">Root cause inferred</span> : null}
        </div>
        <p className="muted">
          Started {clock(d.started_ts)} · {duration(end - d.started_ts)} {resolved ? 'total' : 'so far'} · {ago(now, d.last_alert_ts)} last alert
        </p>
      </header>

      <div className="d-impact">
        <div><b className={d.customers_offline ? 't-down' : ''}>{num(d.customers_offline)}</b><span>offline</span></div>
        <div><b className={d.customers_degraded ? 't-degraded' : ''}>{num(d.customers_degraded)}</b><span>degraded</span></div>
        <div><b>{num(d.business_affected)}</b><span>business and enterprise</span></div>
        <div><b>{num(d.raw_alert_count)}</b><span>raw alerts, 1 incident</span></div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="d-actions">
        {openAlerts > 0 && (
          <button className="btn primary" disabled={busy} onClick={() => act(async () => { await api.restore({ incident_id: id }) })}>
            Restore affected nodes
          </button>
        )}
        {!resolved && (
          <button
            className="btn"
            disabled={busy || openAlerts > 0}
            title={openAlerts > 0 ? `${openAlerts} alerts are still open. Restore the nodes first.` : 'Close this incident now'}
            onClick={() => act(() => api.setStatus(id, 'resolved', 'Marked resolved by engineer'))}
          >
            Mark resolved
          </button>
        )}
      </div>

      <section className="d-sec">
        <div className="sec-head">
          <h3>Customer update</h3>
          <span className="muted small">{SOURCE_LABEL[d.status_update_source] || ''}</span>
        </div>
        {editing ? (
          <textarea className="update-edit" value={draft} onChange={(e) => setDraft(e.target.value)} rows={6} aria-label="Customer update text" />
        ) : (
          <p className="update">{d.status_update}</p>
        )}
        <div className="sec-actions">
          {editing ? (
            <>
              <button className="btn small primary" disabled={busy || !draft.trim()} onClick={() => act(async () => { const r = await api.saveUpdate(id, draft); setEditing(false); return r })}>Save</button>
              <button className="btn small" onClick={() => setEditing(false)}>Cancel</button>
            </>
          ) : (
            <>
              <button className="btn small" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
              <button className="btn small" onClick={() => { setDraft(d.status_update || ''); setEditing(true) }}>Edit</button>
              <button
                className="btn small"
                disabled={busy || !config?.llm_configured}
                title={config?.llm_configured ? 'Ask the AI model to rewrite this update' : 'Set ANTHROPIC_API_KEY or OPENAI_API_KEY on the server to enable this'}
                onClick={() => act(() => api.rewriteUpdate(id, 'ai'))}
              >
                Rewrite with AI
              </button>
              {d.status_update_source !== 'template' && (
                <button className="btn small quiet" disabled={busy} onClick={() => act(() => api.rewriteUpdate(id, 'template'))}>Use template</button>
              )}
            </>
          )}
        </div>
      </section>

      <section className="d-sec">
        <h3>Technical summary</h3>
        <pre className="tech">{d.technical_summary}</pre>
      </section>

      {d.runbook?.length > 0 && !resolved && (
        <section className="d-sec">
          <h3>What to check</h3>
          <ul className="runbook">
            {d.runbook.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </section>
      )}

      <section className="d-sec">
        <h3>Timeline</h3>
        <ol className="timeline">
          {d.events.map((e, i) => (
            <li key={i}>
              <time>{clock(e.ts)}</time>
              <span>{e.message}{e.author !== 'system' && <em> — {e.author}</em>}</span>
            </li>
          ))}
        </ol>
        <form className="note" onSubmit={(ev) => { ev.preventDefault(); if (!note.trim()) return; act(async () => { const r = await api.addNote(id, note.trim()); setNote(''); return r }) }}>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note to the timeline" aria-label="Add a note to the timeline" />
          <button className="btn small" disabled={busy || !note.trim()}>Add note</button>
        </form>
      </section>

      <details className="d-sec">
        <summary>Affected nodes ({d.affected_nodes.length})</summary>
        <ul className="nodes">
          {d.affected_nodes.map((n) => (
            <li key={n.id}><i className={`dot ${n.status}`} aria-hidden="true" />{n.name}<span className="muted"> {n.status === 'down' ? 'down' : 'degraded'}</span></li>
          ))}
          {d.affected_nodes.length === 0 && <li className="muted">None right now.</li>}
        </ul>
      </details>

      <details className="d-sec">
        <summary>Alerts in this incident ({d.alerts.length} unique, {num(d.raw_alert_count)} raw)</summary>
        <ul className="alerts">
          {d.alerts.map((a) => (
            <li key={a.id} className={a.state === 'cleared' ? 'is-cleared' : ''}>
              <time>{clock(a.ts)}</time>
              <span>{TYPE_LABEL[a.type] || a.type} · {a.node_name}{a.count > 1 ? ` · ${a.count} times` : ''}</span>
              <em>{a.state === 'open' ? 'open' : 'cleared'}</em>
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}
