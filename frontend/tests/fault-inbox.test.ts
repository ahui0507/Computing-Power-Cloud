import { describe, expect, it } from 'vitest'
import { acknowledgeFaults, mergeFaultInbox, readIncidents, type FaultIncident } from '../src/utils/faultInbox'

const fault: FaultIncident = { id: 'first', code: 'platform-api', title: '接口异常', message: '检查接口', severity: 'warning',
  active: true, first_seen: 100, last_seen: 110, resolved_at: null }

describe('persistent administrator fault inbox', () => {
  it('retains recovered incidents until manually acknowledged, including across refresh', () => {
    let inbox = mergeFaultInbox({ acknowledged: [], pending: [] }, [fault])
    inbox = JSON.parse(JSON.stringify(inbox))
    inbox = mergeFaultInbox(inbox, [{ ...fault, active: false, resolved_at: 120 }])
    expect(inbox.pending).toHaveLength(1)
    expect(inbox.pending[0].active).toBe(false)
    inbox = acknowledgeFaults(inbox)
    expect(mergeFaultInbox(inbox, [fault]).pending).toHaveLength(0)
    expect(mergeFaultInbox(inbox, [{ ...fault, id: 'recurrence' }]).pending).toHaveLength(1)
    expect(mergeFaultInbox(inbox, [{ ...fault, severity: 'critical' }]).pending).toHaveLength(1)
  })
  it('keeps an unread fault when it disappears from the feed', () => {
    expect(mergeFaultInbox({ acknowledged: [], pending: [fault] }, []).pending).toEqual([fault])
  })
  it('rejects malformed feeds instead of reporting healthy', () => {
    expect(() => readIncidents([{ ...fault, last_seen: 'invalid' }])).toThrow()
  })
})
