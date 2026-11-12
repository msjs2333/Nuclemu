export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}
async function request(path: string, data?: unknown) {
  const response = await fetch('/api/' + path, {
    cache: 'no-store',
    ...(data === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
    }),
  })
  if (!response.ok) {
    const message = await response.json().catch(() => ({}))
    throw new ApiError(response.status, message.error || '请求失败 (' + response.status + ')')
  }
  return response
}
export async function api<T>(path: string, data?: unknown): Promise<T> {
  return (await request(path, data)).json()
}
export async function downloadProducts(data: unknown) {
  const response = await request('download', data)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const legacy = disposition.match(/filename=(?:"([^"]+)"|([^;]+))/i)
  const filename = encoded ? decodeURIComponent(encoded) : legacy?.[1] ?? legacy?.[2]?.trim()
  if (!filename) throw Error('服务未提供下载文件名，请重试。')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 30000)
}
export function downloadExperiment(session: string) {
  return downloadProducts({session, scope: 'experiment'})
}
export async function filePayload(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768))
  return btoa(binary)
}
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error) }
