export type DocumentKind = 'pdf' | 'markdown'

export interface LibraryDocument {
  id: string
  name: string
  title: string
  kind: DocumentKind
  extension: string
  pageCount: number
  charCount: number
  sectionCount: number
  createdAt: string
  lastOpenedAt: string
  progress: number
}

export interface DocumentSection {
  id: string
  title: string
  level: number
  text: string
  order: number
  page?: number
}

export interface OpenDocument extends LibraryDocument {
  text: string
  sections: DocumentSection[]
}

export interface AgentSource {
  source_type: 'paper_internal' | 'web_search'
  content: string
  relevance_score: number
  document_id?: string
  document_title?: string
  section?: string
  page?: number
  title?: string
  url?: string
  provider?: string
}

export interface AgentStatus {
  agent: 'orchestrator' | 'long_context' | 'web_search' | 'fact_check'
  state: 'running' | 'done' | 'skipped'
  detail: string
}

export interface Verification {
  passed: boolean
  confidence: number
  citationCoverage: number
  invalidCitations: number[]
  message: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  imageDataUrl?: string
  statuses?: AgentStatus[]
  paperSources?: AgentSource[]
  webSources?: AgentSource[]
  verification?: Verification
  warning?: string
  streaming?: boolean
  stopped?: boolean
}

export interface ScreenshotAttachment {
  dataUrl: string
  width: number
  height: number
  ocrText: string
}

export interface ProviderCatalogEntry {
  id: string
  name: string
  base_url: string
  key_url: string
  api_style: 'chat_completions' | 'responses'
  needs_base_url: boolean
}

export interface ProviderModel {
  id: string
  name: string
}

export interface ProviderSlot {
  has_key: boolean
  api_key: string
  model: string
  base_url: string
  models: ProviderModel[]
  models_updated_at: string
}

export interface AppSettings {
  provider: string
  api_key: string
  model: string
  base_url: string
  serpapi_key: string
  baidu_translate_appid: string
  baidu_translate_api_key: string
  comment_idle_opacity: number
  web_search: boolean
  fact_check: boolean
  configured: boolean
  translation_configured: boolean
  catalog?: ProviderCatalogEntry[]
  providers?: Record<string, ProviderSlot>
}

export interface TranslationResult {
  source: string
  translation: string
  from: string
  to: string
  provider: 'baidu' | 'local'
  fallback_reason: string
}

export interface TranslationStatus {
  checked: boolean
  provider: 'baidu' | 'local'
  baidu_available: boolean
  baidu_reason: string
  quota_exhausted: boolean
  local_model_state: 'missing' | 'downloading' | 'ready' | 'error'
  local_model_progress: number
  local_model_error: string
}

export type HighlightColor = 'yellow' | 'green' | 'blue' | 'pink' | 'orange'

export interface PdfHighlight {
  id: string
  page: number
  start: number
  end: number
  text: string
  color: HighlightColor
  createdAt: number
}

export interface DoodlePoint {
  x: number
  y: number
}

export interface DoodleStroke {
  id: string
  page: number
  tool: 'brush' | 'eraser'
  color: string
  size: number
  opacity: number
  points: DoodlePoint[]
  createdAt: number
}

export interface MarginComment {
  id: string
  kind: DocumentKind
  page: number
  start: number
  end: number
  text: string
  content: string
  source: 'manual' | 'ai'
  createdAt: number
  updatedAt: number
}

export interface PdfAnnotations {
  highlights: PdfHighlight[]
  doodles: DoodleStroke[]
  comments: MarginComment[]
}
