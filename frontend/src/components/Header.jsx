import { useEffect, useRef, useState } from 'react'
import { ago } from '../fmt'

const Bell = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" />
  </svg>
)
const Speaker = ({ off }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M11 5 6 9H3v6h3l5 4z" />
    {off ? <path d="m16 9 5 6m0-6-5 6" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />}
  </svg>
)

export default function Header({ connected, sound, onSound, notifications, now, onOpenIncident, onMarkRead }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  const unread = notifications.filter((n) => !n.is_read).length

  useEffect(() => {
    if (!open) return
    const close = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false)
    }
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <header className="top">
      <div className="brand">
        <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
          <g stroke="#8DA0BC" strokeWidth="1.5" fill="none">
            <path d="M13 6v7M13 13 6 20M13 13l7 7" />
          </g>
          <circle cx="13" cy="6" r="3.2" fill="#34C6B0" />
          <circle cx="6" cy="20" r="3" fill="#F4B73F" />
          <circle cx="20" cy="20" r="3" fill="#FF5A43" />
        </svg>
        <div>
          <h1>Outage Command Center</h1>
          <p>Faisalabad network · demo data</p>
        </div>
      </div>
      <div className="top-right">
        <span className={`conn ${connected ? 'is-on' : ''}`} role="status">
          <i aria-hidden="true" />
          {connected ? 'Live' : 'Reconnecting'}
        </span>
        <button className="icon-btn" onClick={onSound} aria-pressed={sound} aria-label={sound ? 'Mute alert sound' : 'Turn on alert sound'} title={sound ? 'Alert sound on' : 'Alert sound off'}>
          <Speaker off={!sound} />
        </button>
        <div className="bell" ref={box}>
          <button
            className="icon-btn"
            aria-expanded={open}
            aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}
            onClick={() => setOpen(!open)}
          >
            <Bell />
            {unread > 0 && <span className="badge">{unread > 9 ? '9+' : unread}</span>}
          </button>
          {open && (
            <div className="drop" role="dialog" aria-label="Notifications">
              <div className="drop-head">
                <strong>Notifications</strong>
                <button className="btn quiet small" onClick={onMarkRead} disabled={!unread}>Mark all as read</button>
              </div>
              {notifications.length === 0 ? (
                <p className="drop-empty">Nothing yet. Major and critical incidents show up here.</p>
              ) : (
                <ul>
                  {notifications.map((n) => (
                    <li key={n.id}>
                      <button
                        className={`drop-item lvl-${n.level} ${n.is_read ? '' : 'is-unread'}`}
                        onClick={() => {
                          setOpen(false)
                          if (n.incident_id) onOpenIncident(n.incident_id)
                        }}
                      >
                        <span className="drop-title">{n.title}</span>
                        <span className="drop-body">{n.body}</span>
                        <span className="drop-time">{ago(now, n.ts)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
