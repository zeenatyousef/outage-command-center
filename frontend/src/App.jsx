import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { useLive } from './useLive'
import Header from './components/Header'
import KpiStrip from './components/KpiStrip'
import MapView, { STATUS_COLOR } from './components/MapView'
import SimPanel from './components/SimPanel'
import IncidentList from './components/IncidentList'
import IncidentDetail from './components/IncidentDetail'
import Feed from './components/Feed'
import Toasts from './components/Toasts'

function readSound() {
  try {
    return localStorage.getItem('occ-sound') !== 'off'
  } catch {
    return true
  }
}

export default function App() {
  const [nodes, setNodes] = useState([])
  const [config, setConfig] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('incidents')
  const [toasts, setToasts] = useState([])
  const [sound, setSound] = useState(readSound)
  const [now, setNow] = useState(Date.now() / 1000)
  const audio = useRef(null)
  const soundRef = useRef(sound)
  soundRef.current = sound

  const beep = useCallback((level) => {
    if (!soundRef.current) return
    try {
      audio.current = audio.current || new (window.AudioContext || window.webkitAudioContext)()
      const ctx = audio.current
      const tones = level === 'critical' ? [880, 660, 880] : [660, 880]
      tones.forEach((f, i) => {
        const o = ctx.createOscillator()
        const g = ctx.createGain()
        o.frequency.value = f
        g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.18)
        g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + i * 0.18 + 0.02)
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.18 + 0.16)
        o.connect(g).connect(ctx.destination)
        o.start(ctx.currentTime + i * 0.18)
        o.stop(ctx.currentTime + i * 0.18 + 0.17)
      })
    } catch {
      /* audio is optional */
    }
  }, [])

  const onNotification = useCallback(
    (n) => {
      setToasts((t) => [...t.filter((x) => x.id !== n.id), n].slice(-4))
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== n.id)), 9000)
      if (n.level === 'major' || n.level === 'critical') beep(n.level)
    },
    [beep]
  )

  const live = useLive(onNotification)
  const { statuses, incidents, metrics, feed, notifications, connected } = live

  useEffect(() => {
    api.topology().then((r) => setNodes(r.nodes)).catch(() => {})
    api.config().then(setConfig).catch(() => {})
  }, [])
  // reload static node data after a reconnect so a restarted backend is picked up
  useEffect(() => {
    if (connected) api.topology().then((r) => setNodes(r.nodes)).catch(() => {})
  }, [connected])

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(t)
  }, [])

  const parent = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.parent_id])), [nodes])

  const openIncident = useCallback((id) => {
    setSelectedId(id)
  }, [])

  const onSelectNode = useCallback(
    (nodeId) => {
      const active = incidents.filter((i) => i.status !== 'resolved')
      let cur = nodeId
      while (cur) {
        const hit = active.find((i) => i.root_node_id === cur)
        if (hit) return openIncident(hit.id)
        cur = parent[cur]
      }
    },
    [incidents, parent, openIncident]
  )

  const toggleSound = () => {
    const next = !sound
    setSound(next)
    try {
      localStorage.setItem('occ-sound', next ? 'on' : 'off')
    } catch {
      /* storage can be unavailable */
    }
    if (next) beep('major')
  }

  const reset = async () => {
    await api.reset().catch(() => {})
    live.clearLocal()
    setSelectedId(null)
    setToasts([])
  }

  const markRead = () => {
    live.markAllRead()
    api.markRead().catch(() => {})
  }

  const selected = incidents.find((i) => i.id === selectedId)
  const stamp = selected
    ? [selected.raw_alert_count, selected.status, selected.customers_offline, selected.customers_degraded,
       selected.status_update_source, selected.kind, selected.root_node_id, selected.inferred].join('|')
    : ''
  // if the selected incident was merged away or reset, fall back to the list
  useEffect(() => {
    if (selectedId && connected && incidents.length >= 0 && !selected && metrics) setSelectedId(null)
  }, [selectedId, selected, connected, metrics, incidents.length])

  return (
    <div className="app">
      <Header
        connected={connected}
        sound={sound}
        onSound={toggleSound}
        notifications={notifications}
        now={now}
        onOpenIncident={openIncident}
        onMarkRead={markRead}
      />
      <main className="main">
        <section className="stage">
          <KpiStrip m={metrics} />
          <div className="mapwrap">
            <MapView
              nodes={nodes}
              statuses={statuses}
              incidents={incidents}
              selectedIncidentId={selectedId}
              onSelectNode={onSelectNode}
            />
            <SimPanel nodes={nodes} incidents={incidents} onReset={reset} />
            <ul className="legend" aria-label="Map legend">
              <li><i style={{ background: STATUS_COLOR.up }} />Healthy</li>
              <li><i style={{ background: STATUS_COLOR.degraded }} />Degraded or on backup path</li>
              <li><i style={{ background: STATUS_COLOR.down }} />Down</li>
              <li><i className="legend-backup" />Backup uplink</li>
              <li><i className="legend-ring" />Root cause</li>
            </ul>
            <Toasts toasts={toasts} onOpen={(id) => { setToasts([]); openIncident(id) }} onClose={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
          </div>
        </section>
        <aside className="side">
          {selectedId && selected ? (
            <IncidentDetail id={selectedId} stamp={stamp} config={config} now={now} onBack={() => setSelectedId(null)} />
          ) : (
            <>
              <div className="tabs" role="tablist">
                <button role="tab" aria-selected={tab === 'incidents'} className={tab === 'incidents' ? 'is-on' : ''} onClick={() => setTab('incidents')}>
                  Incidents <span className="count">{incidents.filter((i) => i.status !== 'resolved').length}</span>
                </button>
                <button role="tab" aria-selected={tab === 'feed'} className={tab === 'feed' ? 'is-on' : ''} onClick={() => setTab('feed')}>
                  Raw alerts <span className="count">{metrics ? metrics.raw_alerts : 0}</span>
                </button>
              </div>
              <div className="side-scroll">
                {tab === 'incidents' ? (
                  <IncidentList incidents={incidents} now={now} onOpen={openIncident} />
                ) : (
                  <Feed items={feed} onOpen={(id) => { setTab('incidents'); openIncident(id) }} />
                )}
              </div>
            </>
          )}
        </aside>
      </main>
    </div>
  )
}
