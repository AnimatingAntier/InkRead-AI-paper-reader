import { LoaderCircle, MessageSquareQuote, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { MarginComment } from '../types'

interface Props {
  comment: MarginComment
  index: number
  top: number
  idleOpacity: number
  active: boolean
  onActiveChange: (active: boolean) => void
  onChange: (content: string) => void
  onDelete: () => void
  onGenerate: () => Promise<void>
  onHeightChange?: (height: number) => void
}

export function MarginCommentCard({
  comment,
  index,
  top,
  idleOpacity,
  active,
  onActiveChange,
  onChange,
  onDelete,
  onGenerate,
  onHeightChange,
}: Props) {
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const card = useRef<HTMLElement>(null)
  const onHeightChangeRef = useRef(onHeightChange)
  onHeightChangeRef.current = onHeightChange

  useEffect(() => {
    const element = textarea.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.max(62, element.scrollHeight)}px`
  }, [comment.content, expanded])

  useLayoutEffect(() => {
    const element = card.current
    if (!element) return
    const report = () => onHeightChangeRef.current?.(Math.ceil(element.getBoundingClientRect().height))
    report()
    const observer = new ResizeObserver(report)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const generate = async () => {
    setGenerating(true)
    setError('')
    try {
      await onGenerate()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI 批注生成失败')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <article
      ref={card}
      className={`margin-comment-card ${active ? 'active' : ''} ${expanded ? 'expanded' : ''}`}
      style={
        {
          top,
          '--comment-idle-opacity': idleOpacity,
        } as React.CSSProperties
      }
      onMouseEnter={() => {
        setExpanded(true)
        onActiveChange(true)
      }}
      onMouseLeave={() => {
        setExpanded(false)
        onActiveChange(false)
      }}
      onFocus={() => {
        setExpanded(true)
        onActiveChange(true)
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setExpanded(false)
          onActiveChange(false)
        }
      }}
      data-comment-id={comment.id}
    >
      <span
        className="margin-comment-collapsed"
        title={`批注 N.${index + 1} · 移入展开`}
        aria-label={`展开批注 N.${index + 1}`}
      >
        <MessageSquareQuote size={15} />
        <em>{index + 1}</em>
      </span>
      <header>
        <span><i />批注</span>
        <em>N.{index + 1}</em>
      </header>
      <blockquote title={comment.text}>{comment.text}</blockquote>
      <textarea
        ref={textarea}
        value={comment.content}
        onChange={(event) => onChange(event.target.value)}
        placeholder="点击这里编辑批注，或让 AI 生成…"
        aria-label={`编辑批注 N.${index + 1}`}
      />
      {error && <p className="margin-comment-error">{error}</p>}
      <footer>
        <span>{comment.source === 'ai' ? '✦ 砚读 AI' : '本机手记'}</span>
        <div>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={generating}
            title="让 AI 生成批注"
          >
            {generating ? <LoaderCircle size={12} className="spin" /> : <Sparkles size={12} />}
            AI
          </button>
          <button type="button" onClick={onDelete} title="删除批注">
            <Trash2 size={12} />
          </button>
        </div>
      </footer>
    </article>
  )
}

export function stackCommentTops(
  items: Array<{ id: string; anchorTop: number; contentLength: number; height?: number }>,
): Map<string, number> {
  const positions = new Map<string, number>()
  let nextTop = 8
  items
    .slice()
    .sort((left, right) => left.anchorTop - right.anchorTop)
    .forEach((item) => {
      const top = Math.max(8, item.anchorTop - 24, nextTop)
      positions.set(item.id, top)
      nextTop = top + (item.height || estimateCommentHeight(item.contentLength)) + 14
    })
  return positions
}

export function estimateCommentHeight(contentLength: number): number {
  const extraLines = Math.max(0, Math.ceil(contentLength / 24) - 2)
  return 180 + Math.min(126, extraLines * 18)
}
