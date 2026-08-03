import DOMPurify from 'dompurify'
import katex from 'katex'
import { MessageSquareQuote } from 'lucide-react'
import { marked } from 'marked'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { generateMarginComment, getAnnotations, saveAnnotations } from '../api'
import type { MarginComment, OpenDocument, PdfAnnotations } from '../types'
import {
  estimateCommentHeight,
  MarginCommentCard,
  stackCommentTops,
} from './MarginCommentCard'

interface Props {
  document: OpenDocument
  onProgress: (value: number) => void
  onSelection: (text: string) => void
  scrollTarget?: string
  commentMode: boolean
  onCommentModeChange: (enabled: boolean) => void
  commentIdleOpacity: number
}

interface MarkdownAnchor {
  comment: MarginComment
  rects: Array<{ x: number; y: number; w: number; h: number }>
  anchorTop: number
}

const EMPTY_ANNOTATIONS: PdfAnnotations = { highlights: [], doodles: [], comments: [] }

function generateId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `comment-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function renderMath(markdown: string): string {
  const blocks: string[] = []
  let output = markdown.replace(/\$\$([\s\S]+?)\$\$/g, (_, expression: string) => {
    const index = blocks.length
    blocks.push(
      katex.renderToString(expression.trim(), {
        displayMode: true,
        throwOnError: false,
        strict: false,
      }),
    )
    return `\n<div data-math="${index}"></div>\n`
  })
  output = output.replace(/(?<!\\)\$([^$\n]+?)\$/g, (_, expression: string) =>
    katex.renderToString(expression.trim(), {
      displayMode: false,
      throwOnError: false,
      strict: false,
    }),
  )
  output = output.replace(/<div data-math="(\d+)"><\/div>/g, (_, index: string) => blocks[Number(index)])
  return output
}

function rangeFromOffsets(root: HTMLElement, start: number, end: number): Range | null {
  const walker = window.document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const range = window.document.createRange()
  let offset = 0
  let startNode: Text | null = null
  let endNode: Text | null = null
  let startOffset = 0
  let endOffset = 0
  let node = walker.nextNode() as Text | null
  while (node) {
    const next = offset + node.data.length
    if (!startNode && start >= offset && start <= next) {
      startNode = node
      startOffset = Math.min(node.data.length, start - offset)
    }
    if (end >= offset && end <= next) {
      endNode = node
      endOffset = Math.min(node.data.length, end - offset)
      break
    }
    offset = next
    node = walker.nextNode() as Text | null
  }
  if (!startNode || !endNode) return null
  range.setStart(startNode, startOffset)
  range.setEnd(endNode, endOffset)
  return range
}

function selectionOffsets(root: HTMLElement, selection: Selection) {
  if (!selection.rangeCount || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  const raw = range.toString()
  const text = raw.trim()
  if (text.length < 2) return null
  const prefix = window.document.createRange()
  prefix.selectNodeContents(root)
  prefix.setEnd(range.startContainer, range.startOffset)
  const leading = raw.length - raw.trimStart().length
  const trailing = raw.length - raw.trimEnd().length
  const start = prefix.toString().length + leading
  return { start, end: start + raw.length - leading - trailing, text }
}

export function MarkdownReader({
  document,
  onProgress,
  onSelection,
  scrollTarget,
  commentMode,
  onCommentModeChange,
  commentIdleOpacity,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const main = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const [annotations, setAnnotations] = useState<PdfAnnotations>(EMPTY_ANNOTATIONS)
  const [annotationsLoaded, setAnnotationsLoaded] = useState(false)
  const [revision, setRevision] = useState(0)
  const [activeCommentId, setActiveCommentId] = useState('')
  const [anchors, setAnchors] = useState<MarkdownAnchor[]>([])
  const [commentHeights, setCommentHeights] = useState<Record<string, number>>({})

  const html = useMemo(() => {
    marked.setOptions({ gfm: true, breaks: false })
    const rendered = marked.parse(renderMath(document.text)) as string
    return DOMPurify.sanitize(rendered, {
      ADD_ATTR: ['target', 'rel'],
      ADD_TAGS: ['math', 'semantics', 'annotation'],
    })
  }, [document.id, document.text])

  const comments = useMemo(
    () => annotations.comments.filter((comment) => comment.kind === 'markdown'),
    [annotations.comments],
  )

  useEffect(() => {
    setAnnotations(EMPTY_ANNOTATIONS)
    setAnnotationsLoaded(false)
    setRevision(0)
    setActiveCommentId('')
    setCommentHeights({})
    let cancelled = false
    void getAnnotations(document.id)
      .then((value) => {
        if (!cancelled) {
          setAnnotations({ ...EMPTY_ANNOTATIONS, ...value, comments: value.comments || [] })
          setAnnotationsLoaded(true)
        }
      })
      .catch(() => {
        if (!cancelled) setAnnotationsLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [document.id])

  useEffect(() => {
    if (!annotationsLoaded || revision === 0) return
    const timer = window.setTimeout(() => {
      void saveAnnotations(document.id, annotations)
    }, 480)
    return () => window.clearTimeout(timer)
  }, [annotations, annotationsLoaded, document.id, revision])

  useEffect(() => {
    const root = scroller.current
    if (!root || !scrollTarget) return
    const sections = [...root.querySelectorAll('h1,h2,h3,h4')]
    const sectionId = scrollTarget.split(':')[0]
    const index = document.sections.findIndex((section) => section.id === sectionId)
    const target = sections[Math.max(0, index)]
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [scrollTarget, document.sections])

  const calculateAnchors = useCallback(() => {
    const bodyElement = body.current
    const mainElement = main.current
    if (!bodyElement || !mainElement) return
    const mainBounds = mainElement.getBoundingClientRect()
    const next = comments.flatMap((comment): MarkdownAnchor[] => {
      const range = rangeFromOffsets(bodyElement, comment.start, comment.end)
      if (!range) return []
      const rects = Array.from(range.getClientRects())
        .filter((rect) => rect.width > 0 && rect.height > 0)
        .map((rect) => ({
          x: rect.left - mainBounds.left,
          y: rect.top - mainBounds.top,
          w: rect.width,
          h: rect.height,
        }))
      if (!rects.length) return []
      return [{ comment, rects, anchorTop: rects[0].y }]
    })
    setAnchors(next)
  }, [comments])

  useEffect(() => {
    const frame = window.requestAnimationFrame(calculateAnchors)
    const observer = new ResizeObserver(calculateAnchors)
    if (main.current) observer.observe(main.current)
    if (body.current) observer.observe(body.current)
    window.addEventListener('resize', calculateAnchors)
    void window.document.fonts?.ready.then(calculateAnchors)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
      window.removeEventListener('resize', calculateAnchors)
    }
  }, [calculateAnchors, html])

  const commitAnnotations = useCallback(
    (update: (current: PdfAnnotations) => PdfAnnotations) => {
      setAnnotations(update)
      setRevision((value) => value + 1)
    },
    [],
  )

  const updateComment = useCallback(
    (id: string, values: Partial<MarginComment>) => {
      commitAnnotations((current) => ({
        ...current,
        comments: current.comments.map((comment) =>
          comment.id === id
            ? { ...comment, ...values, updatedAt: Date.now() }
            : comment,
        ),
      }))
    },
    [commitAnnotations],
  )

  const deleteComment = useCallback(
    (id: string) => {
      commitAnnotations((current) => ({
        ...current,
        comments: current.comments.filter((comment) => comment.id !== id),
      }))
      setActiveCommentId((current) => (current === id ? '' : current))
    },
    [commitAnnotations],
  )

  const generateComment = useCallback(
    async (comment: MarginComment) => {
      const result = await generateMarginComment(document.id, comment.text)
      updateComment(comment.id, { content: result.content, source: 'ai' })
    },
    [document.id, updateComment],
  )

  const handleScroll = () => {
    const element = scroller.current
    if (!element) return
    const maximum = element.scrollHeight - element.clientHeight
    onProgress(maximum ? (element.scrollTop / maximum) * 100 : 100)
  }

  const handleSelection = (event: React.MouseEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('.margin-comment-card')) return
    const selection = window.getSelection()
    const bodyElement = body.current
    if (!selection || !bodyElement) return
    const selected = selectionOffsets(bodyElement, selection)
    if (!selected) return
    if (commentMode) {
      const now = Date.now()
      const comment: MarginComment = {
        id: generateId(),
        kind: 'markdown',
        page: 1,
        start: selected.start,
        end: selected.end,
        text: selected.text.slice(0, 8000),
        content: '',
        source: 'manual',
        createdAt: now,
        updatedAt: now,
      }
      commitAnnotations((current) => ({
        ...current,
        comments: [...current.comments, comment],
      }))
      setActiveCommentId(comment.id)
      selection.removeAllRanges()
    } else {
      onSelection(selected.text.slice(0, 8000))
    }
  }

  const commentLayout = useMemo(() => {
    const positions = stackCommentTops(
      anchors.map(({ comment, anchorTop }) => ({
        id: comment.id,
        anchorTop,
        contentLength: comment.content.length,
        height: commentHeights[comment.id],
      })),
    )
    const contentHeight = anchors.reduce((maximum, { comment }) => {
      const top = positions.get(comment.id) || 8
      const height = commentHeights[comment.id] || estimateCommentHeight(comment.content.length)
      return Math.max(maximum, top + height + 18)
    }, 0)
    return { positions, contentHeight }
  }, [anchors, commentHeights])

  const updateCommentHeight = useCallback((id: string, height: number) => {
    setCommentHeights((current) =>
      current[id] === height ? current : { ...current, [id]: height },
    )
  }, [])

  return (
    <div className="markdown-reader">
      <div className="pdf-toolbar markdown-toolbar">
        <div className={`annotation-tools ${commentMode ? 'expanded' : ''}`}>
          <button
            className={commentMode ? 'active' : ''}
            title={commentMode ? '退出批注扫描工具 · Esc' : '批注扫描工具'}
            aria-label={commentMode ? '退出批注' : '批注'}
            aria-pressed={commentMode}
            onClick={() => onCommentModeChange(!commentMode)}
          >
            <MessageSquareQuote size={15} />
          </button>
        </div>
        <span className="markdown-toolbar-hint">
          {commentMode ? '批注扫描中 · 选择文字生成批注' : '选择批注工具后扫描文字'}
        </span>
      </div>
      <div
        className={`reader-scroll markdown-scroll ${commentMode ? 'comment-mode' : ''}`}
        ref={scroller}
        onScroll={handleScroll}
        onMouseUp={handleSelection}
      >
      <article className={`markdown-paper ${comments.length || commentMode ? 'with-comments' : ''}`}>
        <div className="markdown-main" ref={main}>
          <header className="paper-heading">
            <div className="paper-kicker">Markdown · 精排阅读</div>
            <h1>{document.title}</h1>
            <div className="paper-meta">
              {document.sectionCount} 节 · {document.charCount.toLocaleString()} 字符
            </div>
          </header>
          <div
            ref={body}
            className="markdown-body"
            dangerouslySetInnerHTML={{ __html: html }}
            onClick={(event) => {
              const link = (event.target as HTMLElement).closest('a')
              if (link) {
                link.setAttribute('target', '_blank')
                link.setAttribute('rel', 'noreferrer')
              }
            }}
          />
          <div className="markdown-comment-highlights" aria-hidden="true">
            {anchors.flatMap(({ comment, rects }) =>
              rects.map((rect, index) => (
                <span
                  key={`${comment.id}-${index}`}
                  className={`comment-anchor-mark ${
                    activeCommentId === comment.id ? 'active' : ''
                  }`}
                  style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
                />
              )),
            )}
            {anchors.map(({ comment, rects }) => {
              const last = rects.at(-1)
              if (!last) return null
              return (
                <span
                  key={`link-${comment.id}`}
                  className={`margin-comment-link ${
                    activeCommentId === comment.id ? 'active' : ''
                  }`}
                  style={{
                    left: last.x + last.w,
                    top: last.y + last.h / 2,
                    width: Math.max(20, (main.current?.clientWidth || 0) - last.x - last.w + 42),
                  }}
                />
              )
            })}
          </div>
        </div>
        <aside
          className="markdown-margin-comments"
          style={{ minHeight: commentLayout.contentHeight || undefined }}
          aria-label="Markdown 批注"
        >
          {anchors.map(({ comment }, index) => (
            <MarginCommentCard
              key={comment.id}
              comment={comment}
              index={index}
              top={commentLayout.positions.get(comment.id) || 8}
              idleOpacity={commentIdleOpacity}
              active={activeCommentId === comment.id}
              onActiveChange={(active) => setActiveCommentId(active ? comment.id : '')}
              onChange={(content) => updateComment(comment.id, { content, source: 'manual' })}
              onDelete={() => deleteComment(comment.id)}
              onGenerate={() => generateComment(comment)}
              onHeightChange={(height) => updateCommentHeight(comment.id, height)}
            />
          ))}
        </aside>
        </article>
      </div>
    </div>
  )
}
