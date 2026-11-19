import { useCallback, useEffect, useRef, useState } from 'react'

const EMPTY = { connected: false, statuses: {}, incidents: [], metrics: null, feed: [], notifications: [] }

/** Live state from the backend WebSocket, with automatic reconnect. */
export function useLive(onNotification) {
  const [state, setState] = useState(EMPTY)
  const cb = useRef(onNotification)
  cb.current = onNotification

  useEffect(() => {
    let ws
    let timer
    let closed = false
    let tries = 0

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        tries = 0
        setState((s) => ({ ...s, connected: true }))
      }
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }))
        if (!closed) timer = setTimeout(connect, Math.min(5000, 500 * 2 ** tries++))
      }
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data)
        const feed = (m.feed || []).slice().reverse() // server sends oldest first
        if (m.type === 'snapshot') {
          setState((s) => ({
            ...s,
            statuses: m.statuses,
            incidents: m.incidents,
            metrics: m.metrics,
            feed,
            notifications: m.notifications || [],
          }))
        } else if (m.type === 'tick') {
          const fresh = (m.notifications || []).map((n) => ({ ...n, is_read: 0 })).reverse()
          setState((s) => ({
            ...s,
            statuses: m.statuses,
            incidents: m.incidents,
            metrics: m.metrics,
            feed: [...feed, ...s.feed].slice(0, 200),
            notifications: [...fresh, ...s.notifications].slice(0, 50),
          }))
          ;(m.notifications || []).forEach((n) => cb.current?.(n))
        }
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      if (ws) ws.close()
    }
  }, [])

  const clearLocal = useCallback(() => setState((s) => ({ ...s, feed: [], notifications: [] })), [])
  const markAllRead = useCallback(
    () => setState((s) => ({ ...s, notifications: s.notifications.map((n) => ({ ...n, is_read: 1 })) })),
    []
  )
  return { ...state, clearLocal, markAllRead }
}
