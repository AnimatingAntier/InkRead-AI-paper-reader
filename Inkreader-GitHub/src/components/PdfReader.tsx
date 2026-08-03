import {
  Check,
  ChevronLeft,
  ChevronRight,
  Eraser,
  Highlighter,
  LoaderCircle,
  MessageSquareQuote,
  Minus,
  PenLine,
  Plus,
  Undo2,
} from 'lucide-react'
import {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { generateMarginComment, getAnnotations, saveAnnotations } from '../api'
import {
  estimateCommentHeight,
  MarginCommentCard,
  stackCommentTops,
} from './MarginCommentCard'
import type {
  DoodlePoint,
  DoodleStroke,
  HighlightColor,
  MarginComment,
  OpenDocument,
  PdfAnnotations,
  PdfHighlight,
} from '../types'

interface Props {
  document: OpenDocument
  onProgress: (value: number) => void
  onSelection: (text: string) => void
  targetPage?: number
  commentMode: boolean
  onCommentModeChange: (enabled: boolean) => void
  commentIdleOpacity: number
}

interface PdfWord {
  text: string
  x: number
  y: number
  w: number
  h: number
  column?: 'left' | 'right' | 'shared'
}

interface RenderedPage {
  image: string
  width: number
  height: number
  words: PdfWord[]
  columnSplit?: number | null
  pageText: string
  pageCount: number
}

type PdfTool = 'select' | 'highlight' | 'pen'
type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function isEditingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest('input, textarea, select, [contenteditable="true"]'))
  )
}

const EMPTY_ANNOTATIONS: PdfAnnotations = { highlights: [], doodles: [], comments: [] }
const HIGHLIGHT_COLORS: Array<{ key: HighlightColor; value: string; label: string }> = [
  { key: 'yellow', value: 'rgba(245, 205, 64, 0.43)', label: '砚金' },
  { key: 'green', value: 'rgba(86, 155, 113, 0.34)', label: '竹青' },
  { key: 'blue', value: 'rgba(79, 139, 181, 0.31)', label: '天青' },
  { key: 'pink', value: 'rgba(189, 91, 111, 0.31)', label: '胭脂' },
  { key: 'orange', value: 'rgba(218, 139, 55, 0.36)', label: '琥珀' },
]
const PEN_COLORS = [
  { value: '#9f3341', label: '朱砂' },
  { value: '#263a34', label: '墨绿' },
  { value: '#2e4f70', label: '靛青' },
  { value: '#29251f', label: '墨色' },
  { value: '#a0712a', label: '赭金' },
]

function generateId(prefix: string): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function wordRangeRects(words: PdfWord[]) {
  const rects: Array<{ x: number; y: number; w: number; h: number }> = []
  if (!words.length) return rects
  let line = [words[0]]
  words.slice(1).forEach((word) => {
    const previous = line[line.length - 1]
    const sameLine =
      Math.abs(word.y - previous.y) <= Math.max(word.h, previous.h) * 0.72 &&
      word.column === previous.column
    if (sameLine) {
      line.push(word)
    } else {
      const first = line[0]
      const last = line[line.length - 1]
      rects.push({
        x: first.x - 1,
        y: first.y + first.h * 0.1,
        w: last.x + last.w - first.x + 2,
        h: Math.max(...line.map((item) => item.h)) * 0.88,
      })
      line = [word]
    }
  })
  const first = line[0]
  const last = line[line.length - 1]
  rects.push({
    x: first.x - 1,
    y: first.y + first.h * 0.1,
    w: last.x + last.w - first.x + 2,
    h: Math.max(...line.map((item) => item.h)) * 0.88,
  })
  return rects
}

function renderStroke(
  context: CanvasRenderingContext2D,
  stroke: DoodleStroke,
  width: number,
  height: number,
) {
  if (!stroke.points.length) return
  context.save()
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.lineWidth = Math.max(1, stroke.size * width)
  if (stroke.tool === 'eraser') {
    context.globalCompositeOperation = 'destination-out'
    context.globalAlpha = 1
    context.strokeStyle = '#000'
    context.fillStyle = '#000'
  } else {
    context.globalCompositeOperation = 'source-over'
    context.globalAlpha = stroke.opacity
    context.strokeStyle = stroke.color
    context.fillStyle = stroke.color
  }
  const points = stroke.points.map((point) => ({ x: point.x * width, y: point.y * height }))
  if (points.length === 1) {
    context.beginPath()
    context.arc(points[0].x, points[0].y, context.lineWidth / 2, 0, Math.PI * 2)
    context.fill()
  } else {
    context.beginPath()
    context.moveTo(points[0].x, points[0].y)
    points.slice(1).forEach((point) => context.lineTo(point.x, point.y))
    context.stroke()
  }
  context.restore()
}

function eraseHighlightInterval(
  current: PdfAnnotations,
  page: number,
  start: number,
  end: number,
): PdfAnnotations {
  const next: PdfHighlight[] = []
  current.highlights.forEach((highlight) => {
    if (highlight.page !== page || highlight.end <= start || highlight.start >= end) {
      next.push(highlight)
      return
    }
    if (highlight.start < start) {
      next.push({ ...highlight, id: generateId('hl'), end: start })
    }
    if (highlight.end > end) {
      next.push({ ...highlight, id: generateId('hl'), start: end })
    }
  })
  return { ...current, highlights: next }
}

export function PdfReader({
  document,
  onProgress,
  onSelection,
  targetPage,
  commentMode,
  onCommentModeChange,
  commentIdleOpacity,
}: Props) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(0.5)
  const [loading, setLoading] = useState(true)
  const [rendered, setRendered] = useState<RenderedPage | null>(null)
  const [error, setError] = useState('')
  const [tool, setTool] = useState<PdfTool>('select')
  const [highlightColor, setHighlightColor] = useState<HighlightColor>('yellow')
  const [highlightEraser, setHighlightEraser] = useState(false)
  const [penColor, setPenColor] = useState('#9f3341')
  const [penSize, setPenSize] = useState(4)
  const [penEraser, setPenEraser] = useState(false)
  const [annotations, setAnnotations] = useState<PdfAnnotations>(EMPTY_ANNOTATIONS)
  const [annotationsLoaded, setAnnotationsLoaded] = useState(false)
  const [revision, setRevision] = useState(0)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [activeCommentId, setActiveCommentId] = useState('')
  const [commentHeights, setCommentHeights] = useState<Record<string, number>>({})
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [panning, setPanning] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const activeColumnRef = useRef<'left' | 'right' | null>(null)
  const historyRef = useRef<PdfAnnotations[]>([])
  const drawingRef = useRef(false)
  const drawingPointsRef = useRef<DoodlePoint[]>([])
  const highlightEraseActiveRef = useRef(false)
  const highlightEraseTouchedRef = useRef<Set<number>>(new Set())
  const panRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    scrollLeft: number
    scrollTop: number
  } | null>(null)

  useEffect(() => {
    setPage(1)
    setTool('select')
    setAnnotations(EMPTY_ANNOTATIONS)
    setAnnotationsLoaded(false)
    setRevision(0)
    setSaveState('idle')
    setSpaceHeld(false)
    setPanning(false)
    panRef.current = null
    historyRef.current = []
    let cancelled = false
    void getAnnotations(document.id)
      .then((value) => {
        if (!cancelled) {
          setAnnotations({ ...EMPTY_ANNOTATIONS, ...value, comments: value.comments || [] })
          setAnnotationsLoaded(true)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAnnotations(EMPTY_ANNOTATIONS)
          setAnnotationsLoaded(true)
          setSaveState('error')
        }
      })
    return () => {
      cancelled = true
    }
  }, [document.id])

  useEffect(() => {
    if (commentMode) {
      setTool('select')
      setHighlightEraser(false)
      setPenEraser(false)
    }
  }, [commentMode])

  useEffect(() => {
    if (targetPage) setPage(Math.max(1, Math.min(document.pageCount, targetPage)))
  }, [targetPage, document.pageCount])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    fetch(`/api/documents/${document.id}/page/${page}?scale=${(zoom * 1.35).toFixed(2)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.error || 'PDF 页面渲染失败')
        return payload as RenderedPage
      })
      .then((value) => {
        setRendered(value)
        onProgress((page / value.pageCount) * 100)
      })
      .catch((reason) => {
        if ((reason as Error).name !== 'AbortError') {
          setError(reason instanceof Error ? reason.message : 'PDF 页面渲染失败')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [document.id, page, zoom, onProgress])

  useEffect(() => {
    if (!annotationsLoaded || revision === 0) return
    setSaveState('saving')
    const timer = window.setTimeout(() => {
      void saveAnnotations(document.id, annotations)
        .then(() => setSaveState('saved'))
        .catch(() => setSaveState('error'))
    }, 480)
    return () => window.clearTimeout(timer)
  }, [annotations, annotationsLoaded, document.id, revision])

  const commitAnnotations = useCallback(
    (update: (current: PdfAnnotations) => PdfAnnotations) => {
      setAnnotations((current) => {
        historyRef.current = [...historyRef.current, current].slice(-80)
        return update(current)
      })
      setRevision((value) => value + 1)
    },
    [],
  )

  const undo = useCallback(() => {
    const previous = historyRef.current.at(-1)
    if (!previous) return
    historyRef.current = historyRef.current.slice(0, -1)
    setAnnotations(previous)
    setRevision((value) => value + 1)
  }, [])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement | null
      if (element?.matches('input, textarea, select')) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && tool !== 'select') {
        event.preventDefault()
        undo()
      }
      if (event.key === 'Escape' && tool !== 'select') setTool('select')
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [tool, undo])

  useEffect(() => {
    const finishHighlightErase = () => {
      highlightEraseActiveRef.current = false
      highlightEraseTouchedRef.current.clear()
    }
    window.addEventListener('pointerup', finishHighlightErase)
    window.addEventListener('pointercancel', finishHighlightErase)
    window.addEventListener('blur', finishHighlightErase)
    return () => {
      window.removeEventListener('pointerup', finishHighlightErase)
      window.removeEventListener('pointercancel', finishHighlightErase)
      window.removeEventListener('blur', finishHighlightErase)
    }
  }, [])

  const lockSelectionColumn = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (tool === 'pen') return
    const layer = textLayerRef.current
    const split = rendered?.columnSplit
    if (!layer || !split) {
      activeColumnRef.current = null
      layer?.removeAttribute('data-active-column')
      return
    }
    const bounds = layer.getBoundingClientRect()
    const x = event.clientX - bounds.left
    const column = x < split ? 'left' : 'right'
    activeColumnRef.current = column
    layer.dataset.activeColumn = column
  }

  const selectedWordIndices = useCallback((): number[] => {
    const selection = window.getSelection()
    const layer = textLayerRef.current
    if (!selection?.rangeCount || selection.isCollapsed || !layer) return []
    const range = selection.getRangeAt(0)
    const activeColumn = activeColumnRef.current
    return Array.from(layer.querySelectorAll<HTMLSpanElement>('span'))
      .filter((span) => {
        const column = span.dataset.selectionColumn
        if (activeColumn && column !== activeColumn && column !== 'shared') return false
        try {
          return range.intersectsNode(span)
        } catch {
          return false
        }
      })
      .map((span) => Number(span.dataset.wordIndex))
      .filter(Number.isFinite)
      .sort((a, b) => a - b)
  }, [])

  const eraseHighlightRange = useCallback(
    (start: number, end: number) => {
      commitAnnotations((current) => eraseHighlightInterval(current, page, start, end))
    },
    [commitAnnotations, page],
  )

  const eraseHighlightWord = (
    event: ReactPointerEvent<HTMLButtonElement>,
    wordIndex: number,
    begin: boolean,
  ) => {
    if (tool !== 'highlight' || !highlightEraser) return
    if (begin && event.button !== 0) return
    if (!begin && (!highlightEraseActiveRef.current || event.buttons !== 1)) return
    event.preventDefault()
    event.stopPropagation()
    if (begin) {
      highlightEraseActiveRef.current = true
      highlightEraseTouchedRef.current.clear()
    }
    if (highlightEraseTouchedRef.current.has(wordIndex)) return
    highlightEraseTouchedRef.current.add(wordIndex)
    setAnnotations((current) => {
      if (begin) {
        historyRef.current = [...historyRef.current, current].slice(-80)
      }
      return eraseHighlightInterval(current, page, wordIndex, wordIndex + 1)
    })
    setRevision((value) => value + 1)
  }

  const finishSelection = useCallback(() => {
    const indices = selectedWordIndices()
    if (!indices.length || !rendered) return
    const words = indices.map((index) => rendered.words[index]).filter(Boolean)
    const selected = words.map((word) => word.text).join(' ').replace(/\s+/g, ' ').trim()
    const start = indices[0]
    const end = indices[indices.length - 1] + 1
    if (commentMode && selected.length >= 2) {
      const now = Date.now()
      const comment: MarginComment = {
        id: generateId('comment'),
        kind: 'pdf',
        page,
        start,
        end,
        text: selected.slice(0, 8000),
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
      window.getSelection()?.removeAllRanges()
    } else if (tool === 'highlight') {
      if (highlightEraser) {
        eraseHighlightRange(start, end)
      } else {
        commitAnnotations((current) => ({
          ...current,
          highlights: [
            ...current.highlights,
            {
              id: generateId('hl'),
              page,
              start,
              end,
              text: selected,
              color: highlightColor,
              createdAt: Date.now(),
            },
          ],
        }))
      }
      window.getSelection()?.removeAllRanges()
    } else if (tool === 'select' && selected.length >= 2) {
      onSelection(selected.slice(0, 8000))
    }
  }, [
    commitAnnotations,
    commentMode,
    eraseHighlightRange,
    highlightColor,
    highlightEraser,
    onSelection,
    page,
    rendered,
    selectedWordIndices,
    tool,
  ])

  const highlightRects = useMemo(() => {
    if (!rendered) return []
    return annotations.highlights
      .filter(
        (highlight) =>
          highlight.page === page &&
          highlight.start >= 0 &&
          highlight.end <= rendered.words.length &&
          highlight.start < highlight.end,
      )
      .map((highlight) => {
        const words = rendered.words.slice(highlight.start, highlight.end)
        return {
          ...highlight,
          value:
            HIGHLIGHT_COLORS.find((color) => color.key === highlight.color)?.value ||
            HIGHLIGHT_COLORS[0].value,
          rects: wordRangeRects(words),
        }
      })
  }, [annotations.highlights, page, rendered])

  const commentAnchors = useMemo(() => {
    if (!rendered) return []
    return annotations.comments
      .filter(
        (comment) =>
          comment.kind === 'pdf' &&
          comment.page === page &&
          comment.start >= 0 &&
          comment.end <= rendered.words.length &&
          comment.start < comment.end,
      )
      .map((comment) => {
        const rects = wordRangeRects(rendered.words.slice(comment.start, comment.end))
        const totalWidth = rects.reduce((sum, rect) => sum + rect.w, 0)
        const centerX = totalWidth
          ? rects.reduce((sum, rect) => sum + (rect.x + rect.w / 2) * rect.w, 0) / totalWidth
          : rendered.width / 2
        return {
          comment,
          rects,
          anchorTop: rects[0]?.y || 0,
          side: centerX < rendered.width / 2 ? 'left' as const : 'right' as const,
        }
      })
  }, [annotations.comments, page, rendered])

  const commentLayout = useMemo(() => {
    const positions = new Map<string, number>()
    let contentHeight = rendered?.height || 0
    const sideCounts = { left: 0, right: 0 }
    ;(['left', 'right'] as const).forEach((side) => {
      const lane = commentAnchors.filter((anchor) => anchor.side === side)
      sideCounts[side] = lane.length
      const tops = stackCommentTops(
        lane.map(({ comment, anchorTop }) => ({
          id: comment.id,
          anchorTop,
          contentLength: comment.content.length,
          height: commentHeights[comment.id],
        })),
      )
      lane.forEach(({ comment }) => {
        const top = tops.get(comment.id) || 8
        positions.set(comment.id, top)
        contentHeight = Math.max(
          contentHeight,
          top + (commentHeights[comment.id] || estimateCommentHeight(comment.content.length)) + 18,
        )
      })
    })
    return { positions, contentHeight, sideCounts }
  }, [commentAnchors, commentHeights, rendered?.height])

  const updateCommentHeight = useCallback((id: string, height: number) => {
    setCommentHeights((current) =>
      current[id] === height ? current : { ...current, [id]: height },
    )
  }, [])

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

  const highlightEraserTargets = useMemo(() => {
    if (!rendered || tool !== 'highlight' || !highlightEraser) return []
    const targets = new Map<
      number,
      { index: number; x: number; y: number; w: number; h: number }
    >()
    annotations.highlights
      .filter((highlight) => highlight.page === page)
      .forEach((highlight) => {
        const start = Math.max(0, highlight.start)
        const end = Math.min(rendered.words.length, highlight.end)
        for (let index = start; index < end; index += 1) {
          const word = rendered.words[index]
          if (!word) continue
          targets.set(index, {
            index,
            x: word.x - 1,
            y: word.y + word.h * 0.06,
            w: word.w + 2,
            h: word.h * 0.94,
          })
        }
      })
    return Array.from(targets.values())
  }, [annotations.highlights, highlightEraser, page, rendered, tool])

  const renderDoodles = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !rendered) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(rendered.width * dpr)
    canvas.height = Math.round(rendered.height * dpr)
    const context = canvas.getContext('2d')
    if (!context) return
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    context.clearRect(0, 0, rendered.width, rendered.height)
    annotations.doodles
      .filter((stroke) => stroke.page === page)
      .forEach((stroke) => renderStroke(context, stroke, rendered.width, rendered.height))
  }, [annotations.doodles, page, rendered])

  useEffect(() => {
    renderDoodles()
  }, [renderDoodles])

  const pointerPoint = (event: ReactPointerEvent<HTMLCanvasElement>): DoodlePoint | null => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return null
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    }
  }

  const drawLiveSegment = (points: DoodlePoint[]) => {
    const canvas = canvasRef.current
    if (!canvas || !rendered || !points.length) return
    const context = canvas.getContext('2d')
    if (!context) return
    renderStroke(
      context,
      {
        id: 'preview',
        page,
        tool: penEraser ? 'eraser' : 'brush',
        color: penColor,
        size: (penEraser ? Math.max(18, penSize * 4) : penSize) / rendered.width,
        opacity: 0.92,
        points,
        createdAt: Date.now(),
      },
      rendered.width,
      rendered.height,
    )
  }

  const penPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (tool !== 'pen' || event.button !== 0) return
    const point = pointerPoint(event)
    if (!point) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    drawingRef.current = true
    drawingPointsRef.current = [point]
    drawLiveSegment([point])
  }

  const penPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return
    const point = pointerPoint(event)
    if (!point) return
    event.preventDefault()
    const points = drawingPointsRef.current
    const previous = points.at(-1)
    if (previous && Math.hypot(point.x - previous.x, point.y - previous.y) < 0.0008) return
    points.push(point)
    drawLiveSegment(previous ? [previous, point] : [point])
  }

  const penPointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current || !rendered) return
    drawingRef.current = false
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // Pointer capture may already be released by the platform.
    }
    const points = drawingPointsRef.current
    drawingPointsRef.current = []
    if (!points.length) return
    const stroke: DoodleStroke = {
      id: generateId('stroke'),
      page,
      tool: penEraser ? 'eraser' : 'brush',
      color: penColor,
      size: (penEraser ? Math.max(18, penSize * 4) : penSize) / rendered.width,
      opacity: 0.92,
      points,
      createdAt: Date.now(),
    }
    commitAnnotations((current) => ({ ...current, doodles: [...current.doodles, stroke] }))
  }

  const numPages = rendered?.pageCount || document.pageCount || 1

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      if (isEditingTarget(event.target)) return
      if (window.document.querySelector('.modal-backdrop, .screenshot-overlay')) return
      if (!event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) {
        if (event.key === 'ArrowLeft') {
          event.preventDefault()
          setPage((value) => Math.max(1, value - 1))
          return
        }
        if (event.key === 'ArrowRight') {
          event.preventDefault()
          setPage((value) => Math.min(numPages, value + 1))
          return
        }
      }
      if (
        event.code === 'Space' &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        event.preventDefault()
        setSpaceHeld(true)
      }
    }
    const keyUp = (event: KeyboardEvent) => {
      if (event.code !== 'Space') return
      setSpaceHeld(false)
      setPanning(false)
      panRef.current = null
    }
    const blur = () => {
      setSpaceHeld(false)
      setPanning(false)
      panRef.current = null
    }
    window.addEventListener('keydown', keyDown)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', keyDown)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('blur', blur)
    }
  }, [numPages])

  const startCanvasPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!spaceHeld || event.button !== 0) return
    const scroller = scrollRef.current
    if (!scroller) return
    event.preventDefault()
    event.stopPropagation()
    window.getSelection()?.removeAllRanges()
    scroller.setPointerCapture(event.pointerId)
    panRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: scroller.scrollLeft,
      scrollTop: scroller.scrollTop,
    }
    setPanning(true)
  }

  const moveCanvasPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const pan = panRef.current
    const scroller = scrollRef.current
    if (!pan || !scroller || pan.pointerId !== event.pointerId) return
    event.preventDefault()
    scroller.scrollLeft = pan.scrollLeft - (event.clientX - pan.startX)
    scroller.scrollTop = pan.scrollTop - (event.clientY - pan.startY)
  }

  const finishCanvasPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const pan = panRef.current
    if (!pan || pan.pointerId !== event.pointerId) return
    event.preventDefault()
    event.stopPropagation()
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // Pointer capture may already have been released by the platform.
    }
    panRef.current = null
    setPanning(false)
  }

  return (
    <div className={`pdf-reader tool-${tool} ${commentMode ? 'comment-mode' : ''}`}>
      <div className="pdf-toolbar">
        <div className="page-tools">
          <button
            aria-label="上一页"
            title="上一页 · ←"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            <ChevronLeft size={16} />
          </button>
          <label>
            <input
              value={page}
              onChange={(event) => {
                const value = Number(event.target.value)
                if (Number.isFinite(value)) setPage(Math.max(1, Math.min(numPages, value)))
              }}
            />
            <span>/ {numPages}</span>
          </label>
          <button
            aria-label="下一页"
            title="下一页 · →"
            disabled={page >= numPages}
            onClick={() => setPage((value) => Math.min(numPages, value + 1))}
          >
            <ChevronRight size={16} />
          </button>
        </div>

        <div className={`annotation-tools ${tool !== 'select' || commentMode ? 'expanded' : ''}`}>
          <button
            className={tool === 'highlight' ? 'active' : ''}
            title={tool === 'highlight' ? '退出荧光笔' : '荧光笔'}
            aria-pressed={tool === 'highlight'}
            onClick={() => {
              onCommentModeChange(false)
              setTool((current) => (current === 'highlight' ? 'select' : 'highlight'))
            }}
          >
            <Highlighter size={15} />
          </button>
          <button
            className={tool === 'pen' ? 'active' : ''}
            title={tool === 'pen' ? '退出画笔' : '画笔'}
            aria-pressed={tool === 'pen'}
            onClick={() => {
              onCommentModeChange(false)
              setTool((current) => (current === 'pen' ? 'select' : 'pen'))
            }}
          >
            <PenLine size={15} />
          </button>
          <button
            className={commentMode ? 'active' : ''}
            title={commentMode ? '退出批注扫描工具 · Esc' : '批注扫描工具'}
            aria-label={commentMode ? '退出批注' : '批注'}
            aria-pressed={commentMode}
            onClick={() => {
              setTool('select')
              setHighlightEraser(false)
              setPenEraser(false)
              onCommentModeChange(!commentMode)
            }}
          >
            <MessageSquareQuote size={15} />
          </button>

          {tool === 'highlight' && (
            <div className="tool-options">
              <span className="tool-swatches">
                {HIGHLIGHT_COLORS.map((color) => (
                  <button
                    key={color.key}
                    className={!highlightEraser && highlightColor === color.key ? 'selected' : ''}
                    style={{ '--swatch': color.value } as React.CSSProperties}
                    title={color.label}
                    onClick={() => {
                      setHighlightColor(color.key)
                      setHighlightEraser(false)
                    }}
                  />
                ))}
              </span>
              <i />
              <button
                className={highlightEraser ? 'active' : ''}
                title="擦除高亮"
                onClick={() => setHighlightEraser((value) => !value)}
              >
                <Eraser size={14} />
              </button>
            </div>
          )}

          {tool === 'pen' && (
            <div className="tool-options">
              <span className="tool-swatches pen">
                {PEN_COLORS.map((color) => (
                  <button
                    key={color.value}
                    className={!penEraser && penColor === color.value ? 'selected' : ''}
                    style={{ '--swatch': color.value } as React.CSSProperties}
                    title={color.label}
                    onClick={() => {
                      setPenColor(color.value)
                      setPenEraser(false)
                    }}
                  />
                ))}
              </span>
              <label
                className="pen-size-slider"
                title={`画笔粗细 ${penSize}px`}
                style={
                  {
                    '--pen-size-position': `${((penSize - 1) / 19) * 100}%`,
                  } as React.CSSProperties
                }
              >
                <input
                  type="range"
                  min="1"
                  max="20"
                  step="0.5"
                  value={penSize}
                  aria-label="连续调节画笔粗细"
                  onChange={(event) => setPenSize(Number(event.target.value))}
                />
                <output>{Number.isInteger(penSize) ? penSize : penSize.toFixed(1)}</output>
              </label>
              <i />
              <button
                className={penEraser ? 'active' : ''}
                title="橡皮擦"
                onClick={() => setPenEraser((value) => !value)}
              >
                <Eraser size={14} />
              </button>
            </div>
          )}

          {tool !== 'select' && (
            <>
              <button disabled={!historyRef.current.length} title="撤回一步 · Ctrl+Z" onClick={undo}>
                <Undo2 size={14} />
              </button>
              <span className={`annotation-save-state ${saveState}`} title="标注自动保存">
                {saveState === 'saving' ? (
                  <LoaderCircle size={12} className="spin" />
                ) : saveState === 'error' ? (
                  '!'
                ) : (
                  <Check size={12} />
                )}
              </span>
            </>
          )}
        </div>

        <div className="zoom-tools">
          <button aria-label="缩小" onClick={() => setZoom((value) => Math.max(0.55, value - 0.1))}>
            <Minus size={15} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button aria-label="放大" onClick={() => setZoom((value) => Math.min(2.4, value + 0.1))}>
            <Plus size={15} />
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className={`pdf-scroll ${spaceHeld ? 'pan-ready' : ''} ${panning ? 'panning' : ''}`}
        onPointerDownCapture={startCanvasPan}
        onPointerMove={moveCanvasPan}
        onPointerUp={finishCanvasPan}
        onPointerCancel={finishCanvasPan}
        onMouseDown={(event) => {
          if (!spaceHeld) lockSelectionColumn(event)
        }}
        onMouseUp={() => {
          if (!panning) finishSelection()
        }}
      >
        <div
          className="pdf-page-cluster"
          style={{
            width: rendered
              ? rendered.width +
                (commentLayout.sideCounts.left ? 266 : 0) +
                (commentLayout.sideCounts.right ? 266 : 0)
              : undefined,
            minHeight: commentLayout.contentHeight || undefined,
          }}
        >
        <div
          className="pdf-page"
          style={{
            opacity: loading ? 0.72 : 1,
            width: rendered?.width,
            height: rendered?.height,
            marginLeft: commentLayout.sideCounts.left ? 266 : 0,
            marginRight: 0,
          }}
        >
          {rendered && <img src={rendered.image} width={rendered.width} height={rendered.height} />}

          {rendered && (
            <div
              className={`pdf-highlight-layer ${
                highlightEraser && tool === 'highlight' ? 'erasing' : ''
              }`}
            >
              {highlightRects.flatMap((highlight) =>
                highlight.rects.map((rect, index) => (
                  <span
                    key={`${highlight.id}-${index}`}
                    className="highlight-mark"
                    style={{
                      left: rect.x,
                      top: rect.y,
                      width: rect.w,
                      height: rect.h,
                      background: highlight.value,
                    }}
                    title={highlight.text}
                  />
                )),
              )}
              {commentAnchors.flatMap(({ comment, rects }) =>
                rects.map((rect, index) => (
                  <span
                    key={`comment-mark-${comment.id}-${index}`}
                    className={`comment-anchor-mark ${
                      activeCommentId === comment.id ? 'active' : ''
                    }`}
                    style={{
                      left: rect.x,
                      top: rect.y,
                      width: rect.w,
                      height: rect.h,
                    }}
                  />
                )),
              )}
              {highlightEraserTargets.map((target) => (
                <button
                  key={`erase-${target.index}`}
                  className="highlight-erase-target"
                  style={{
                    left: target.x,
                    top: target.y,
                    width: target.w,
                    height: target.h,
                  }}
                  title="按住并拖动，可逐词擦除高亮"
                  onPointerDown={(event) => eraseHighlightWord(event, target.index, true)}
                  onPointerEnter={(event) => eraseHighlightWord(event, target.index, false)}
                  onDragStart={(event) => event.preventDefault()}
                />
              ))}
            </div>
          )}

          {rendered && (
            <div
              ref={textLayerRef}
              className="pdf-text-layer"
              style={{ width: rendered.width, height: rendered.height }}
            >
              {rendered.words.map((word, index) => (
                <span
                  key={`${index}-${word.x}-${word.y}`}
                  data-word-index={index}
                  data-selection-column={word.column || 'shared'}
                  style={{
                    left: word.x,
                    top: word.y,
                    width: word.w,
                    height: word.h,
                    fontSize: word.h,
                  }}
                >
                  {word.text}{' '}
                </span>
              ))}
            </div>
          )}

          {rendered && (
            <canvas
              ref={canvasRef}
              className={`pdf-doodle-layer ${tool === 'pen' ? 'active' : ''} ${penEraser ? 'eraser' : ''}`}
              style={{ width: rendered.width, height: rendered.height }}
              onPointerDown={penPointerDown}
              onPointerMove={penPointerMove}
              onPointerUp={penPointerUp}
              onPointerCancel={penPointerUp}
            />
          )}

          {rendered && commentAnchors.length > 0 && (
            <svg
              className="pdf-comment-connectors"
              width={
                rendered.width +
                (commentLayout.sideCounts.left ? 266 : 0) +
                (commentLayout.sideCounts.right ? 266 : 0)
              }
              height={commentLayout.contentHeight}
              style={{
                left: commentLayout.sideCounts.left ? -266 : 0,
              }}
              aria-hidden="true"
            >
              {commentAnchors.map(({ comment, rects, side }) => {
                const anchorRect = side === 'left' ? rects[0] : rects.at(-1)
                if (!anchorRect) return null
                const pageOffset = commentLayout.sideCounts.left ? 266 : 0
                const anchorX =
                  pageOffset +
                  (side === 'left' ? anchorRect.x : anchorRect.x + anchorRect.w)
                const anchorY = anchorRect.y + anchorRect.h / 2
                const targetY = (commentLayout.positions.get(comment.id) || 8) + 27
                const gutterX =
                  pageOffset + (side === 'left' ? -9 : rendered.width + 9)
                const targetX =
                  pageOffset + (side === 'left' ? -18 : rendered.width + 18)
                return (
                  <g
                    key={`comment-connector-${comment.id}`}
                    className={activeCommentId === comment.id ? 'active' : ''}
                  >
                    <path
                      d={`M ${anchorX} ${anchorY} H ${gutterX} V ${targetY} H ${targetX}`}
                    />
                    <circle cx={targetX} cy={targetY} r="3.5" />
                  </g>
                )
              })}
            </svg>
          )}

          {rendered && (['left', 'right'] as const).map((side) => {
            const lane = commentAnchors.filter((anchor) => anchor.side === side)
            if (!lane.length) return null
            return (
              <aside
                key={side}
                className={`pdf-margin-comments side-${side}`}
                style={{
                  left: side === 'left' ? -266 : rendered.width + 18,
                  height: commentLayout.contentHeight,
                }}
                aria-label={`PDF ${side === 'left' ? '左侧' : '右侧'}批注`}
              >
                {lane.map(({ comment }) => (
                  <MarginCommentCard
                    key={comment.id}
                    comment={comment}
                    index={commentAnchors.findIndex((anchor) => anchor.comment.id === comment.id)}
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
            )
          })}

          {loading && (
            <div className="pdf-loading">
              <LoaderCircle size={22} className="spin" />
              正在排印第 {page} 页
            </div>
          )}
          {error && <div className="pdf-error">{error}</div>}
        </div>
        </div>
      </div>
    </div>
  )
}
