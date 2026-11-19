export default function Toasts({ toasts, onOpen, onClose }) {
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((t) => (
        <div key={t.id} className={`toast lvl-${t.level}`} role="alert">
          <button className="toast-main" onClick={() => onOpen(t.incident_id)}>
            <span className="toast-title">{t.title}</span>
            <span className="toast-body">{t.body}</span>
          </button>
          <button className="toast-x" onClick={() => onClose(t.id)} aria-label="Dismiss notification">×</button>
        </div>
      ))}
    </div>
  )
}
