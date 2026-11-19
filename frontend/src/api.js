async function request(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let detail = ''
    try {
      detail = (await r.json()).detail
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail || `Request failed (${r.status})`)
  }
  return r.json()
}

const send = (method) => (url, body) =>
  request(url, {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
const post = send('POST')
const put = send('PUT')

export const api = {
  config: () => request('/api/config'),
  topology: () => request('/api/topology'),
  incident: (id) => request(`/api/incidents/${id}`),
  simulate: (body) => post('/api/simulate', body),
  restore: (body) => post('/api/restore', body),
  reset: () => post('/api/reset'),
  setStatus: (id, status, note) => post(`/api/incidents/${id}/status`, { status, note }),
  addNote: (id, message) => post(`/api/incidents/${id}/notes`, { message }),
  rewriteUpdate: (id, mode) => post(`/api/incidents/${id}/status-update`, { mode }),
  saveUpdate: (id, text) => put(`/api/incidents/${id}/status-update`, { text }),
  markRead: () => post('/api/notifications/read'),
}
