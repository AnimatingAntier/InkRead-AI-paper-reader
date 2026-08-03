import html2canvas from 'html2canvas'
import { LoaderCircle, ScanLine, X } from 'lucide-react'
import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'
import type { ScreenshotAttachment } from '../types'

interface Props {
  target: HTMLElement
  onConfirm: (attachment: ScreenshotAttachment) => void
  onCancel: () => void
}

interface Point {
  x: number
  y: number
}

interface Selection {
  start: Point
  end: Point
}

function intersects(a: DOMRect, b: DOMRect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}

function extractVisibleText(target: HTMLElement, selection: DOMRect): string {
  const pdfWords = Array.from(
    target.querySelectorAll<HTMLSpanElement>('.pdf-text-layer span[data-word-index]'),
  )
    .filter((span) => intersects(span.getBoundingClientRect(), selection))
    .sort(
      (a, b) =>
        Number(a.dataset.wordIndex || 0) - Number(b.dataset.wordIndex || 0),
    )
  if (pdfWords.length) {
    return pdfWords
      .map((span) => span.textContent || '')
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 16_000)
  }

  const markdown = target.querySelector('.markdown-paper')
  if (!markdown) return ''
  const walker = document.createTreeWalker(markdown, NodeFilter.SHOW_TEXT)
  const parts: string[] = []
  let node = walker.nextNode()
  while (node) {
    const value = node.textContent?.replace(/\s+/g, ' ').trim()
    if (value) {
      const range = document.createRange()
      range.selectNodeContents(node)
      if (Array.from(range.getClientRects()).some((rect) => intersects(rect, selection))) {
        parts.push(value)
      }
    }
    node = walker.nextNode()
  }
  return parts.join(' ').replace(/\s+/g, ' ').trim().slice(0, 16_000)
}

export function ScreenshotOverlay({ target, onConfirm, onCancel }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const snapshotRef = useRef<HTMLCanvasElement | null>(null)
  const boundsRef = useRef<DOMRect | null>(null)
  const selectionRef = useRef<Selection | null>(null)
  const draggingRef = useRef(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const snapshot = snapshotRef.current
    if (!canvas || !snapshot) return
    if (canvas.width !== snapshot.width || canvas.height !== snapshot.height) {
      canvas.width = snapshot.width
      canvas.height = snapshot.height
    }
    const context = canvas.getContext('2d')
    if (!context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    context.drawImage(snapshot, 0, 0)
    context.fillStyle = 'rgba(24, 20, 15, 0.48)'
    context.fillRect(0, 0, canvas.width, canvas.height)
    if (!selection) return

    const x = Math.min(selection.start.x, selection.end.x)
    const y = Math.min(selection.start.y, selection.end.y)
    const width = Math.abs(selection.end.x - selection.start.x)
    const height = Math.abs(selection.end.y - selection.start.y)
    if (!width || !height) return
    context.drawImage(snapshot, x, y, width, height, x, y, width, height)
    context.strokeStyle = '#a33242'
    context.lineWidth = Math.max(2, canvas.width / 900)
    context.setLineDash([9, 5])
    context.strokeRect(x, y, width, height)
    context.setLineDash([])
  }, [selection])

  useEffect(() => {
    let cancelled = false
    const captureTarget =
      target.querySelector<HTMLElement>('.pdf-page') ||
      target.querySelector<HTMLElement>('.markdown-scroll') ||
      target
    const bounds = captureTarget.getBoundingClientRect()
    boundsRef.current = bounds
    void html2canvas(captureTarget, {
      backgroundColor: null,
      scale: Math.min(1.75, Math.max(1, window.devicePixelRatio || 1)),
      useCORS: true,
      logging: false,
      imageTimeout: 6000,
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
      scrollX: -window.scrollX,
      scrollY: -window.scrollY,
    })
      .then((snapshot) => {
        if (cancelled) return
        snapshotRef.current = snapshot
        setReady(true)
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '无法捕获论文阅读区')
        }
      })
    return () => {
      cancelled = true
    }
  }, [target])

  useEffect(() => {
    draw()
  }, [draw, ready])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const pointFromEvent = (event: ReactPointerEvent<HTMLCanvasElement>): Point | null => {
    const snapshot = snapshotRef.current
    const bounds = boundsRef.current
    if (!snapshot || !bounds || !bounds.width || !bounds.height) return null
    return {
      x: Math.max(
        0,
        Math.min(snapshot.width, (event.clientX - bounds.left) * (snapshot.width / bounds.width)),
      ),
      y: Math.max(
        0,
        Math.min(snapshot.height, (event.clientY - bounds.top) * (snapshot.height / bounds.height)),
      ),
    }
  }

  const pointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!ready || event.button !== 0) return
    const point = pointFromEvent(event)
    if (!point) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    draggingRef.current = true
    const next = { start: point, end: point }
    selectionRef.current = next
    setSelection(next)
  }

  const pointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!draggingRef.current || !selectionRef.current) return
    const point = pointFromEvent(event)
    if (!point) return
    event.preventDefault()
    const next = { ...selectionRef.current, end: point }
    selectionRef.current = next
    setSelection(next)
  }

  const pointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // The platform may already have released capture.
    }
    const current = selectionRef.current
    const snapshot = snapshotRef.current
    const bounds = boundsRef.current
    if (!current || !snapshot || !bounds) return
    const x = Math.round(Math.min(current.start.x, current.end.x))
    const y = Math.round(Math.min(current.start.y, current.end.y))
    const width = Math.round(Math.abs(current.end.x - current.start.x))
    const height = Math.round(Math.abs(current.end.y - current.start.y))
    if (width < 18 || height < 18) {
      selectionRef.current = null
      setSelection(null)
      return
    }

    const maximum = 1800
    const outputScale = Math.min(1, maximum / Math.max(width, height))
    const output = document.createElement('canvas')
    output.width = Math.max(1, Math.round(width * outputScale))
    output.height = Math.max(1, Math.round(height * outputScale))
    output
      .getContext('2d')
      ?.drawImage(snapshot, x, y, width, height, 0, 0, output.width, output.height)

    const cssScaleX = bounds.width / snapshot.width
    const cssScaleY = bounds.height / snapshot.height
    const selectedClientRect = new DOMRect(
      bounds.left + x * cssScaleX,
      bounds.top + y * cssScaleY,
      width * cssScaleX,
      height * cssScaleY,
    )
    onConfirm({
      dataUrl: output.toDataURL('image/png'),
      width: output.width,
      height: output.height,
      ocrText: extractVisibleText(target, selectedClientRect),
    })
  }

  const bounds = boundsRef.current || target.getBoundingClientRect()
  return (
    <div className="screenshot-overlay" aria-label="论文截图框选">
      <div className="screenshot-hint">
        <ScanLine size={15} />
        <span>{ready ? '拖拽框选论文区域' : '正在准备截图…'}</span>
        <small>ESC 取消</small>
        <button onClick={onCancel} title="取消截图">
          <X size={14} />
        </button>
      </div>
      {error ? (
        <div className="screenshot-error">
          <b>截图准备失败</b>
          <span>{error}</span>
          <button onClick={onCancel}>返回阅读</button>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          className={ready ? 'screenshot-canvas ready' : 'screenshot-canvas'}
          style={{
            left: bounds.left,
            top: bounds.top,
            width: bounds.width,
            height: bounds.height,
          }}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerUp={pointerUp}
          onPointerCancel={pointerUp}
        />
      )}
      {!ready && !error && <LoaderCircle className="screenshot-spinner spin" size={24} />}
    </div>
  )
}
