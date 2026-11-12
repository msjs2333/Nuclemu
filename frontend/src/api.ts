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
export async function downloadProducts(data: unknown, fallback: string) {
  const response = await request('download', data)
  const encoded = response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = encoded ? decodeURIComponent(encoded) : fallback
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 30000)
}
export function downloadExperiment(session: string) {
  return downloadProducts({session, scope: 'experiment'}, 'experiment.nuclemu')
}
export async function filePayload(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768))
  return btoa(binary)
}
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error) }
