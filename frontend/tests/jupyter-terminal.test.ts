import { describe, expect, it, vi } from 'vitest'
import { createJupyterTerminal } from '../src/utils/jupyter-terminal'

describe('instance terminal connection', () => {
  it('uses the instance token and preserves the Ingress path', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ name: '2' }) })
    const signal = new AbortController().signal
    const result = await createJupyterTerminal(
      'http://platform.test/jupyter/154/?token=instance-token', signal, fetcher,
    )
    expect(fetcher).toHaveBeenCalledWith('http://platform.test/jupyter/154/api/terminals', {
      method: 'POST', headers: { Authorization: 'token instance-token' }, signal,
    })
    expect(result).toBe('http://platform.test/jupyter/154/terminals/2?token=instance-token')
  })

  it('supports a NodePort instance without an Ingress prefix', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ name: '1' }) })
    const result = await createJupyterTerminal('http://node.test:32001/?token=example', undefined, fetcher)
    expect(result).toBe('http://node.test:32001/terminals/1?token=example')
  })

  it('rejects missing credentials before making a terminal request', async () => {
    const fetcher = vi.fn()
    await expect(createJupyterTerminal('http://platform.test/jupyter/154/', undefined, fetcher))
      .rejects.toThrow('访问地址无效')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('reports a rejected terminal request instead of navigating to an empty terminal', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false })
    await expect(createJupyterTerminal('http://platform.test/jupyter/154/?token=example', undefined, fetcher))
      .rejects.toThrow('终端连接失败')
  })

  it('does not accept a terminal name that escapes its instance path', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ name: '../other' }) })
    await expect(createJupyterTerminal('http://platform.test/jupyter/154/?token=example', undefined, fetcher))
      .rejects.toThrow('终端创建结果无效')
  })
})
