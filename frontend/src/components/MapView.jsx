import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { num } from '../fmt'

export const STATUS_COLOR = { up: '#34C6B0', degraded: '#F4B73F', down: '#FF5A43' }
const RADIUS = { core: 9, hub: 8, tower: 6, cabinet: 3.6 }
const STATUS_TEXT = { up: 'Healthy', degraded: 'Degraded', down: 'Down' }

export default function MapView({ nodes, statuses, incidents, selectedIncidentId, onSelectNode }) {
  const el = useRef(null)
  const map = useRef(null)
  const layers = useRef({ markers: {}, lines: {}, rings: {}, extra: [] })
  const statusRef = useRef(statuses)
  const onSelect = useRef(onSelectNode)
  onSelect.current = onSelectNode
  statusRef.current = statuses
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes])

  // create the map once
  useEffect(() => {
    // zoomSnap 0.25 lets fitBounds choose a zoom that fits beside the simulator panel instead of rounding down
    const m = L.map(el.current, { zoomControl: false, preferCanvas: true, zoomSnap: 0.25 }).setView([31.45, 73.135], 12)
    L.control.zoom({ position: 'bottomright' }).addTo(m)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(m)
    map.current = m
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      m.remove()
      map.current = null
    }
  }, [])

  // draw the topology when it loads
  useEffect(() => {
    const m = map.current
    if (!m || !nodes.length) return
    const ls = layers.current
    Object.values(ls.markers).forEach((x) => x.remove())
    Object.values(ls.lines).forEach((x) => x.remove())
    ls.extra.forEach((x) => x.remove())
    ls.markers = {}
    ls.lines = {}
    ls.extra = []

    nodes.forEach((n) => {
      if (n.parent_id && byId[n.parent_id]) {
        const p = byId[n.parent_id]
        ls.lines[n.id] = L.polyline([[p.lat, p.lng], [n.lat, n.lng]], {
          weight: n.type === 'cabinet' ? 1.5 : 2.5,
          color: STATUS_COLOR.up,
          opacity: 0.4,
          interactive: false,
        }).addTo(m)
      }
      if (n.backup_parent_id && byId[n.backup_parent_id]) {
        const b = byId[n.backup_parent_id]
        ls.extra.push(
          L.polyline([[b.lat, b.lng], [n.lat, n.lng]], {
            weight: 1.5, color: '#A58BFF', opacity: 0.6, dashArray: '4 6', interactive: false,
          }).addTo(m)
        )
      }
    })
    nodes.forEach((n) => {
      const mk = L.circleMarker([n.lat, n.lng], {
        radius: RADIUS[n.type],
        weight: 2,
        color: '#0E1A2B',
        fillColor: STATUS_COLOR.up,
        fillOpacity: 1,
      }).addTo(m)
      mk.bindTooltip(
        () => {
          const s = statusRef.current[n.id] || 'up'
          return `<strong>${n.name}</strong><br/>${STATUS_TEXT[s]} · ${num(n.customers)} customers directly attached`
        },
        { sticky: true, direction: 'top', className: 'occ-tip', opacity: 1 }
      )
      mk.on('click', () => onSelect.current?.(n.id))
      ls.markers[n.id] = mk
    })
    // leave room on the left for the simulator panel on wide screens
    const wide = window.innerWidth > 820 // same breakpoint where the simulator panel starts open
    m.fitBounds(L.latLngBounds(nodes.map((n) => [n.lat, n.lng])), {
      paddingTopLeft: [wide ? 340 : 32, 32],
      paddingBottomRight: [32, 64],
    })
  }, [nodes, byId])

  // colour nodes and links by status
  useEffect(() => {
    const ls = layers.current
    Object.entries(ls.markers).forEach(([id, mk]) => {
      const s = statuses[id] || 'up'
      mk.setStyle({ fillColor: STATUS_COLOR[s] })
      mk.setRadius(RADIUS[byId[id].type] + (s === 'down' ? 2 : 0))
    })
    Object.entries(ls.lines).forEach(([id, ln]) => {
      const s = statuses[id] || 'up'
      ln.setStyle({ color: STATUS_COLOR[s], opacity: s === 'up' ? 0.4 : 0.95 })
    })
  }, [statuses, byId, nodes])

  // rings around the root cause of every active incident
  useEffect(() => {
    const m = map.current
    if (!m) return
    const rings = layers.current.rings
    const active = incidents.filter((i) => i.status !== 'resolved' && byId[i.root_node_id])
    const wanted = new Set(active.map((i) => i.root_node_id))
    Object.keys(rings).forEach((id) => {
      if (!wanted.has(id)) {
        rings[id].remove()
        delete rings[id]
      }
    })
    active.forEach((inc) => {
      const n = byId[inc.root_node_id]
      const cls = `root-ring ${inc.severity} ${inc.inferred ? 'inferred' : ''} ${inc.id === selectedIncidentId ? 'selected' : ''}`
      const icon = L.divIcon({ className: '', html: `<div class="${cls}"></div>`, iconSize: [48, 48] })
      if (rings[n.id]) rings[n.id].setIcon(icon)
      else rings[n.id] = L.marker([n.lat, n.lng], { icon, interactive: false, keyboard: false }).addTo(m)
    })
  }, [incidents, selectedIncidentId, byId, nodes])

  // bring the selected incident's root into view
  useEffect(() => {
    const m = map.current
    const inc = incidents.find((i) => i.id === selectedIncidentId)
    if (!m || !inc || !byId[inc.root_node_id]) return
    const n = byId[inc.root_node_id]
    m.panTo([n.lat, n.lng], { animate: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIncidentId])

  return <div ref={el} className="map" role="application" aria-label="Network map" />
}
