const nf = new Intl.NumberFormat('en-US')
export const num = (n) => nf.format(n ?? 0)

export function ago(now, ts) {
  if (!ts) return ''
  const s = Math.max(0, Math.round(now - ts))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  return `${Math.floor(m / 60)}h ${m % 60}m ago`
}

export function duration(sec) {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export const clock = (ts) =>
  new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

export const STATUS_LABEL = { investigating: 'Investigating', mitigated: 'Recovering', resolved: 'Resolved' }
export const KIND_LABEL = { outage: 'Outage', degradation: 'Degraded service', flapping: 'Flapping link' }
export const TYPE_LABEL = {
  LINK_DOWN: 'Link down',
  POWER_FAILURE: 'Power failure',
  NODE_UNREACHABLE: 'Unreachable',
  HIGH_LATENCY: 'High latency',
  PACKET_LOSS: 'Packet loss',
  CLEARED: 'Recovered',
}
export const RESULT_LABEL = {
  new: 'New',
  deduplicated: 'Collapsed',
  duplicate: 'Collapsed',
  cleared: 'Recovered',
  ignored: 'Ignored',
}
export const SOURCE_LABEL = { template: 'Template draft', ai: 'Written by AI', edited: 'Edited by you' }
