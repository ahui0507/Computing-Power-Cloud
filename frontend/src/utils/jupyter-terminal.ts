/** Create an authenticated terminal inside the user's Jupyter instance. */
export async function createJupyterTerminal(
  jupyterUrl: string,
  signal?: AbortSignal,
  fetcher: typeof fetch = fetch,
): Promise<string> {
  const base = new URL(jupyterUrl)
  const token = base.searchParams.get('token')
  if (!['http:', 'https:'].includes(base.protocol) || !token) {
    throw new Error('实例终端访问地址无效，请返回实例列表刷新')
  }
  if (!base.pathname.endsWith('/')) base.pathname += '/'
  base.search = ''
  base.hash = ''
  const endpoint = new URL('api/terminals', base)
  const response = await fetcher(endpoint.href, {
    method: 'POST',
    headers: { Authorization: `token ${token}` },
    signal,
  })
  if (!response.ok) throw new Error('终端连接失败，请稍后重试')
  const terminal: { name?: unknown } = await response.json()
  if (typeof terminal.name !== 'string' || !/^[A-Za-z0-9_-]+$/.test(terminal.name)) {
    throw new Error('终端创建结果无效，请重试')
  }
  const destination = new URL(`terminals/${terminal.name}`, base)
  destination.searchParams.set('token', token)
  return destination.href
}
