import type {
  AgentSource,
  AgentStatus,
  AppSettings,
  ChatMessage,
  LibraryDocument,
  OpenDocument,
  PdfAnnotations,
  ProviderCatalogEntry,
  ProviderSlot,
  TranslationResult,
  TranslationStatus,
  Verification,
} from './types'

const API_BASE = '/api'

async function responseJson<T>(response: Response): Promise<T> {
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`)
  return payload as T
}

export async function listDocuments(): Promise<LibraryDocument[]> {
  const result = await responseJson<{ documents: LibraryDocument[] }>(
    await fetch(`${API_BASE}/documents`),
  )
  return result.documents
}

export async function openDocument(id: string): Promise<OpenDocument> {
  return responseJson<OpenDocument>(await fetch(`${API_BASE}/documents/${id}`))
}

export async function importDocument(file: File): Promise<LibraryDocument> {
  return responseJson<LibraryDocument>(
    await fetch(`${API_BASE}/documents/import?name=${encodeURIComponent(file.name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    }),
  )
}

export async function deleteDocument(id: string): Promise<void> {
  await responseJson(await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' }))
}

export async function saveProgress(id: string, progress: number): Promise<void> {
  await fetch(`${API_BASE}/documents/${id}/progress`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ progress }),
  })
}

export async function getAnnotations(id: string): Promise<PdfAnnotations> {
  return responseJson<PdfAnnotations>(
    await fetch(`${API_BASE}/documents/${id}/annotations`),
  )
}

export async function saveAnnotations(
  id: string,
  annotations: PdfAnnotations,
): Promise<PdfAnnotations> {
  return responseJson<PdfAnnotations>(
    await fetch(`${API_BASE}/documents/${id}/annotations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(annotations),
    }),
  )
}

export async function generateMarginComment(
  documentId: string,
  selectedText: string,
): Promise<{ content: string }> {
  return responseJson<{ content: string }>(
    await fetch(`${API_BASE}/annotations/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: documentId,
        selected_text: selectedText,
      }),
    }),
  )
}

export async function getSettings(): Promise<AppSettings> {
  return responseJson<AppSettings>(await fetch(`${API_BASE}/settings`))
}

export async function saveSettings(settings: Partial<AppSettings>): Promise<AppSettings> {
  return responseJson<AppSettings>(
    await fetch(`${API_BASE}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }),
  )
}

export async function getProviders(): Promise<{
  catalog: ProviderCatalogEntry[]
  providers: Record<string, ProviderSlot>
}> {
  return responseJson(await fetch(`${API_BASE}/providers`))
}

export async function translateText(text: string, signal?: AbortSignal): Promise<TranslationResult> {
  return responseJson<TranslationResult>(
    await fetch(`${API_BASE}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal,
    }),
  )
}

export async function getTranslationStatus(force = false): Promise<TranslationStatus> {
  const query = force ? '?force=1' : ''
  return responseJson<TranslationStatus>(
    await fetch(`${API_BASE}/translation/status${query}`),
  )
}

export type AgentEvent =
  | ({ type: 'agent_status' } & AgentStatus)
  | {
      type: 'sources'
      paper: AgentSource[]
      web: AgentSource[]
      classification: { intent: string; needs_web: boolean; document_count: number }
    }
  | { type: 'content'; text: string }
  | ({ type: 'verification' } & Verification)
  | { type: 'warning'; message: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export async function* streamAgent(input: {
  message: string
  document_ids: string[]
  selected_text: string
  web_search: boolean
  history: ChatMessage[]
  image_data_url?: string
  image_ocr_text?: string
}, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      ...input,
      history: input.history.map(({ role, content }) => ({ role, content })),
    }),
  })
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.error || 'AI 服务连接失败')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const packets = buffer.split('\n\n')
    buffer = packets.pop() || ''
    for (const packet of packets) {
      const line = packet.split('\n').find((part) => part.startsWith('data:'))
      if (!line) continue
      yield JSON.parse(line.slice(5).trim()) as AgentEvent
    }
  }
}
