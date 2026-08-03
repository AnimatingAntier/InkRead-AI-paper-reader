import { FormEvent, memo, useEffect, useMemo, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Globe2,
  Image,
  LoaderCircle,
  ScanText,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  X,
} from 'lucide-react'
import { streamAgent } from '../api'
import type {
  AgentStatus,
  ChatMessage,
  OpenDocument,
  ScreenshotAttachment,
} from '../types'

interface Props {
  activeDocument: OpenDocument | null
  comparisonDocuments: string[]
  selectedText: string
  onClearSelection: () => void
  screenshot: ScreenshotAttachment | null
  onClearScreenshot: () => void
}

const agentNames: Record<AgentStatus['agent'], string> = {
  orchestrator: '调度中枢',
  long_context: '长上下文',
  web_search: '网络检索',
  fact_check: '事实校验',
}

const MessageContent = memo(function MessageContent({ content }: { content: string }) {
  const html = useMemo(
    () =>
      DOMPurify.sanitize(marked.parse(content, { gfm: true, breaks: true }) as string, {
        ADD_ATTR: ['target', 'rel'],
      }),
    [content],
  )
  return <div className="assistant-markdown" dangerouslySetInnerHTML={{ __html: html }} />
})

function AgentTrace({ statuses }: { statuses: AgentStatus[] }) {
  const [open, setOpen] = useState(true)
  if (!statuses.length) return null
  const active = statuses.find((status) => status.state === 'running')
  return (
    <div className="agent-trace">
      <button className="trace-head" onClick={() => setOpen((value) => !value)}>
        <span>
          {active ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}
          {active ? `${agentNames[active.agent]}正在工作` : 'Agent 协作轨迹'}
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="trace-list">
          {statuses.map((status, index) => (
            <div className={`trace-row ${status.state}`} key={`${status.agent}-${index}`}>
              {status.state === 'running' ? (
                <LoaderCircle size={12} className="spin" />
              ) : status.state === 'done' ? (
                <Check size={12} />
              ) : (
                <Circle size={9} />
              )}
              <b>{agentNames[status.agent]}</b>
              <span>{status.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function AssistantPanel({
  activeDocument,
  comparisonDocuments,
  selectedText,
  onClearSelection,
  screenshot,
  onClearScreenshot,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const [sending, setSending] = useState(false)
  const messagesRef = useRef<HTMLDivElement>(null)
  const requestControllerRef = useRef<AbortController | null>(null)

  useEffect(() => () => requestControllerRef.current?.abort(), [])

  const scrollBottom = () => {
    requestAnimationFrame(() => {
      if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    })
  }

  const ask = async (question: string) => {
    const imageToSend = screenshot
    const value =
      question.trim() ||
      (imageToSend
        ? '请解读这张论文截图，说明其中的文字、图表或公式表达了什么。'
        : '')
    if (!value || sending || !activeDocument) return
    const user: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: value,
      imageDataUrl: imageToSend?.dataUrl,
    }
    const assistant: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      statuses: [],
      streaming: true,
    }
    const history = [...messages, user]
    setMessages((current) => [...current, user, assistant])
    setInput('')
    setSending(true)
    const controller = new AbortController()
    requestControllerRef.current = controller
    if (imageToSend) onClearScreenshot()
    scrollBottom()

    const updateAssistant = (updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((current) =>
        current.map((message) => (message.id === assistant.id ? updater(message) : message)),
      )
      scrollBottom()
    }

    try {
      const ids = Array.from(new Set([activeDocument.id, ...comparisonDocuments]))
      for await (const event of streamAgent(
        {
          message: value,
          document_ids: ids,
          selected_text: selectedText,
          web_search: webSearch,
          history,
          image_data_url: imageToSend?.dataUrl,
          image_ocr_text: imageToSend?.ocrText,
        },
        controller.signal,
      )) {
        if (event.type === 'agent_status') {
          updateAssistant((message) => {
            const statuses = [...(message.statuses || [])]
            const prior = statuses.findIndex(
              (item) => item.agent === event.agent && item.state === 'running',
            )
            if (prior >= 0 && event.state !== 'running') statuses.splice(prior, 1)
            statuses.push(event)
            return { ...message, statuses }
          })
        } else if (event.type === 'sources') {
          updateAssistant((message) => ({
            ...message,
            paperSources: event.paper,
            webSources: event.web,
          }))
        } else if (event.type === 'content') {
          updateAssistant((message) => ({ ...message, content: message.content + event.text }))
        } else if (event.type === 'verification') {
          updateAssistant((message) => ({
            ...message,
            verification: {
              passed: event.passed,
              confidence: event.confidence,
              citationCoverage: event.citationCoverage,
              invalidCitations: event.invalidCitations,
              message: event.message,
            },
          }))
        } else if (event.type === 'warning') {
          updateAssistant((message) => ({ ...message, warning: event.message }))
        } else if (event.type === 'error') {
          throw new Error(event.message)
        }
      }
      updateAssistant((message) => ({ ...message, streaming: false }))
    } catch (error) {
      if (controller.signal.aborted) {
        updateAssistant((message) => ({
          ...message,
          streaming: false,
          stopped: true,
          statuses: (message.statuses || []).map((status) =>
            status.state === 'running'
              ? { ...status, state: 'skipped', detail: '用户已暂停生成' }
              : status,
          ),
        }))
      } else {
        updateAssistant((message) => ({
          ...message,
          streaming: false,
          warning: error instanceof Error ? error.message : 'AI 请求失败',
          content: message.content || '请求没有完成，请检查接口设置后重试。',
        }))
      }
    } finally {
      if (requestControllerRef.current === controller) requestControllerRef.current = null
      setSending(false)
      if (selectedText) onClearSelection()
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void ask(input)
  }

  const stopGenerating = () => {
    requestControllerRef.current?.abort()
  }

  return (
    <aside className="assistant-panel">
      <div className="assistant-head">
        <div className="assistant-orb">
          <Sparkles size={15} />
        </div>
        <div>
          <strong>砚读 AI 助手</strong>
          <span>
            {activeDocument
              ? `已索引本文${comparisonDocuments.length ? ` · 对比 ${comparisonDocuments.length + 1} 篇` : ''}`
              : '等待选择论文'}
          </span>
        </div>
        <i className={activeDocument ? 'online' : ''} />
      </div>

      <div className="assistant-messages" ref={messagesRef}>
        {!messages.length && (
          <div className="assistant-greeting">
            <div className="greeting-mark">砚</div>
            <p>
              {activeDocument
                ? `我已为《${activeDocument.title}》建立独立上下文。可以问核心贡献、公式直觉、实验可信度，或启用联网检索追踪后续工作。`
                : '先从文库导入并打开一篇 PDF 或 Markdown 论文，我会完成解析、检索与可追溯问答。'}
            </p>
          </div>
        )}
        {messages.map((message) => (
          <div className={`chat-message ${message.role}`} key={message.id}>
            {message.role === 'assistant' && (
              <div className="chat-avatar">
                <Bot size={14} />
              </div>
            )}
            <div className="chat-bubble">
              {message.role === 'assistant' && <AgentTrace statuses={message.statuses || []} />}
              {message.imageDataUrl && (
                <img className="chat-screenshot" src={message.imageDataUrl} alt="论文截图" />
              )}
              {message.content ? <MessageContent content={message.content} /> : null}
              {message.streaming && !message.content ? (
                <div className="thinking">
                  <i />
                  <i />
                  <i />
                </div>
              ) : null}
              {message.warning && <div className="chat-warning">{message.warning}</div>}
              {message.stopped && (
                <div className="generation-stopped">
                  <Square size={9} fill="currentColor" />
                  生成已暂停 · 已保留当前内容
                </div>
              )}
              {message.verification && (
                <div className={`verification ${message.verification.passed ? 'passed' : 'review'}`}>
                  <ShieldCheck size={14} />
                  <span>
                    {message.verification.passed ? '已核验' : '需复核'} · 置信{' '}
                    {Math.round(message.verification.confidence * 100)}%
                  </span>
                  <small>{message.verification.message}</small>
                </div>
              )}
              {(message.paperSources?.length || message.webSources?.length) ? (
                <details className="source-drawer">
                  <summary>
                    {message.paperSources?.length || 0} 条原文 · {message.webSources?.length || 0}{' '}
                    条网络来源
                  </summary>
                  <div className="source-groups">
                    {message.paperSources?.slice(0, 6).map((source, index) => (
                      <div className="source-card paper-source" key={`p-${index}`}>
                        <b>[P{index + 1}] {source.section}</b>
                        <span>
                          {source.document_title}
                          {source.page ? ` · 第 ${source.page} 页` : ''}
                        </span>
                      </div>
                    ))}
                    {message.webSources?.map((source, index) => (
                      <a
                        className="source-card web-source"
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        key={`w-${index}`}
                      >
                        <b>[W{index + 1}] {source.title}</b>
                        <span>{source.provider}</span>
                      </a>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {activeDocument && !messages.length && (
        <div className="prompt-chips">
          {['一句话总结本文', '核心方法是什么？', '实验有哪些局限？', '查找后续相关工作'].map(
            (question) => (
              <button key={question} onClick={() => void ask(question)}>
                ✦ {question}
              </button>
            ),
          )}
        </div>
      )}

      {selectedText && (
        <div className="selection-context">
          <span>已引用选区</span>
          <p>{selectedText.slice(0, 110)}{selectedText.length > 110 ? '…' : ''}</p>
          <button onClick={onClearSelection}>移除</button>
        </div>
      )}

      {screenshot && (
        <div className="screenshot-attachment">
          <img src={screenshot.dataUrl} alt="待发送的论文截图" />
          <div>
            <span><Image size={12} />论文截图已就绪</span>
            <small>
              {screenshot.width} × {screenshot.height}
              {screenshot.ocrText ? ` · 本机文字层 ${screenshot.ocrText.length} 字` : ''}
            </small>
            <p><ScanText size={11} />视觉模型直接识图，文本模型自动使用本机 OCR</p>
          </div>
          <button type="button" onClick={onClearScreenshot} title="移除截图">
            <X size={13} />
          </button>
        </div>
      )}

      <form className="assistant-input" onSubmit={submit}>
        <div className="input-actions">
          <button
            type="button"
            className={webSearch ? 'active' : ''}
            onClick={() => setWebSearch((value) => !value)}
            title="联网检索学术资料"
          >
            <Globe2 size={14} />
            联网
          </button>
          <span>论文原文与网络来源严格隔离</span>
        </div>
        <div className="input-row">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                if (input.trim() || screenshot) void ask(input)
              }
            }}
            placeholder={
              screenshot
                ? '输入关于截图的问题，或直接发送…'
                : activeDocument
                  ? '提问本文的任何细节…'
                  : '请先打开一篇论文'
            }
            disabled={!activeDocument || sending}
            rows={1}
          />
          <button
            className={`send-button ${sending ? 'stop-generation' : ''}`}
            type={sending ? 'button' : 'submit'}
            disabled={!sending && (!activeDocument || (!input.trim() && !screenshot))}
            title={
              sending
                ? '暂停生成并保留当前回答'
                : screenshot
                  ? '上传截图并提问'
                  : '发送问题'
            }
            aria-label={sending ? '暂停生成' : '发送问题'}
            onClick={sending ? stopGenerating : undefined}
          >
            {sending ? <Square size={13} fill="currentColor" /> : <Send size={17} />}
          </button>
        </div>
      </form>
    </aside>
  )
}
