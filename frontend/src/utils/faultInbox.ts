export interface FaultIncident {
  id: string
  code: string
  title: string
  message: string
  severity: 'warning' | 'critical'
  active: boolean
  first_seen: number
  last_seen: number
  resolved_at: number | null
}

export interface FaultInbox {
  acknowledged: string[]
  pending: FaultIncident[]
}

export const incidentKey = (incident: FaultIncident) => `${incident.id}:${incident.severity}`

export function readIncidents(value: unknown): FaultIncident[] {
  if (!Array.isArray(value)) throw new Error('Invalid incident feed')
  return value.slice(-200).map((item) => {
    if (!item || typeof item.id !== 'string' || typeof item.code !== 'string' ||
        typeof item.title !== 'string' || typeof item.message !== 'string' ||
        !['warning', 'critical'].includes(item.severity) || typeof item.active !== 'boolean' ||
        !Number.isFinite(item.first_seen) || !Number.isFinite(item.last_seen) ||
        !(item.resolved_at === null || Number.isFinite(item.resolved_at))) {
      throw new Error('Invalid incident')
    }
    return item as FaultIncident
  })
}

export function mergeFaultInbox(inbox: FaultInbox, incidents: FaultIncident[]): FaultInbox {
  const pending = new Map(inbox.pending.map((item) => [incidentKey(item), item]))
  for (const incident of incidents) {
    const key = incidentKey(incident)
    if (!inbox.acknowledged.includes(key)) pending.set(key, incident)
  }
  return { acknowledged: inbox.acknowledged, pending: [...pending.values()].slice(-200) }
}

export function acknowledgeFaults(inbox: FaultInbox): FaultInbox {
  return { acknowledged: [...new Set([...inbox.acknowledged, ...inbox.pending.map(incidentKey)])].slice(-1000), pending: [] }
}
