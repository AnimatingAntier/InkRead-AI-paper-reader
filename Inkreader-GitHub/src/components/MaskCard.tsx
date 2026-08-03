import { Eye, EyeOff, GripHorizontal, X } from 'lucide-react'
import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react'

type MaskMode = 'opaque' | 'transparent'
type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

interface Props {
  visible: boolean
  topOffset: number
  onClose: () => void
}

interface Point {
  x: number
  y: number
}

interface CardSize {
  width: number
  height: number
}

const MIN_WIDTH = 150
const MIN_HEIGHT = 84
const EDGE_GAP = 12

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

export function MaskCard({ visible, topOffset, onClose }: Props) {
  const layer = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<MaskMode>('opaque')
  const [position, setPosition] = useState<Point>({ x: 72, y: 70 })
  const [size, setSize] = useState<CardSize>({ width: 360, height: 220 })

  const resetCard = useCallback(() => {
    const bounds = layer.current?.getBoundingClientRect()
    const availableWidth = bounds?.width || 720
    const availableHeight = bounds?.height || 600
    const width = Math.min(380, Math.max(MIN_WIDTH, availableWidth - EDGE_GAP * 2))
    const height = Math.min(230, Math.max(MIN_HEIGHT, availableHeight - EDGE_GAP * 2))
    setMode('opaque')
    setSize({ width, height })
    setPosition({
      x: Math.max(EDGE_GAP, (availableWidth - width) / 2),
      y: Math.max(EDGE_GAP, Math.min(76, (availableHeight - height) / 2)),
    })
  }, [])

  useEffect(() => {
    if (!visible) return
    const frame = window.requestAnimationFrame(resetCard)
    return () => window.cancelAnimationFrame(frame)
  }, [visible, resetCard])

  useEffect(() => {
    if (!visible) return
    const handleKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName
      const editing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (event.key === 'Tab' && !editing) {
        event.preventDefault()
        setMode((current) => (current === 'opaque' ? 'transparent' : 'opaque'))
      }
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [visible, onClose])

  useEffect(() => {
    if (!visible) return
    const keepInside = () => {
      const bounds = layer.current?.getBoundingClientRect()
      if (!bounds) return
      setSize((current) => ({
        width: Math.min(current.width, Math.max(MIN_WIDTH, bounds.width - EDGE_GAP * 2)),
        height: Math.min(current.height, Math.max(MIN_HEIGHT, bounds.height - EDGE_GAP * 2)),
      }))
      setPosition((current) => ({
        x: clamp(current.x, EDGE_GAP, bounds.width - size.width - EDGE_GAP),
        y: clamp(current.y, EDGE_GAP, bounds.height - size.height - EDGE_GAP),
      }))
    }
    window.addEventListener('resize', keepInside)
    const observer = new ResizeObserver(keepInside)
    if (layer.current) observer.observe(layer.current)
    return () => {
      window.removeEventListener('resize', keepInside)
      observer.disconnect()
    }
  }, [visible, size.width, size.height])

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    const bounds = layer.current?.getBoundingClientRect()
    if (!bounds) return
    const start = { x: event.clientX, y: event.clientY }
    const origin = position
    const handleMove = (moveEvent: PointerEvent) => {
      setPosition({
        x: clamp(
          origin.x + moveEvent.clientX - start.x,
          EDGE_GAP,
          bounds.width - size.width - EDGE_GAP,
        ),
        y: clamp(
          origin.y + moveEvent.clientY - start.y,
          EDGE_GAP,
          bounds.height - size.height - EDGE_GAP,
        ),
      })
    }
    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleUp)
    }
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp)
    window.addEventListener('pointercancel', handleUp)
  }

  const startResize =
    (direction: ResizeDirection) => (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      event.stopPropagation()
      const bounds = layer.current?.getBoundingClientRect()
      if (!bounds) return
      const start = { x: event.clientX, y: event.clientY }
      const origin = position
      const originalSize = size

      const handleMove = (moveEvent: PointerEvent) => {
        const dx = moveEvent.clientX - start.x
        const dy = moveEvent.clientY - start.y
        let x = origin.x
        let y = origin.y
        let width = originalSize.width
        let height = originalSize.height

        if (direction.includes('e')) {
          width = clamp(originalSize.width + dx, MIN_WIDTH, bounds.width - origin.x - EDGE_GAP)
        }
        if (direction.includes('s')) {
          height = clamp(originalSize.height + dy, MIN_HEIGHT, bounds.height - origin.y - EDGE_GAP)
        }
        if (direction.includes('w')) {
          const right = origin.x + originalSize.width
          x = clamp(origin.x + dx, EDGE_GAP, right - MIN_WIDTH)
          width = right - x
        }
        if (direction.includes('n')) {
          const bottom = origin.y + originalSize.height
          y = clamp(origin.y + dy, EDGE_GAP, bottom - MIN_HEIGHT)
          height = bottom - y
        }

        setPosition({ x, y })
        setSize({ width, height })
      }
      const handleUp = () => {
        window.removeEventListener('pointermove', handleMove)
        window.removeEventListener('pointerup', handleUp)
        window.removeEventListener('pointercancel', handleUp)
      }
      window.addEventListener('pointermove', handleMove)
      window.addEventListener('pointerup', handleUp)
      window.addEventListener('pointercancel', handleUp)
    }

  if (!visible) return null

  const toggleMode = () =>
    setMode((current) => (current === 'opaque' ? 'transparent' : 'opaque'))

  return (
    <div
      ref={layer}
      className="mask-card-layer"
      style={{ top: topOffset }}
      aria-label="论文遮挡卡区域"
    >
      <section
        className={`mask-card ${mode}`}
        data-mode={mode}
        style={{
          left: position.x,
          top: position.y,
          width: size.width,
          height: size.height,
        }}
        aria-label={mode === 'opaque' ? '不透明遮挡卡' : '透明遮挡卡'}
      >
        <div className="mask-card-surface">
          <div className="mask-card-drag" onPointerDown={startDrag}>
            <GripHorizontal size={18} />
          </div>
          <div className="mask-card-actions">
            <button
              type="button"
              className="mask-card-mode"
              onClick={toggleMode}
              title={mode === 'opaque' ? '切换为透明模式 · Tab' : '切换为不透明模式 · Tab'}
            >
              {mode === 'opaque' ? <Eye size={14} /> : <EyeOff size={14} />}
              {mode === 'opaque' ? '查看' : '遮挡'}
            </button>
            <button type="button" className="mask-card-close" onClick={onClose} title="关闭遮挡卡 · Esc">
              <X size={14} />
            </button>
          </div>
          <div className="mask-card-copy">
            <b>{mode === 'opaque' ? '内容已遮挡' : '透明查看模式'}</b>
            <span>{mode === 'opaque' ? '先回忆，再揭晓' : '点击“遮挡”继续复习'}</span>
          </div>
          <small className="mask-card-shortcuts">拖动卡片 · 边缘缩放 · Tab 切换</small>
        </div>
        {(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as ResizeDirection[]).map(
          (direction) => (
            <div
              key={direction}
              className={`mask-resize mask-resize-${direction}`}
              onPointerDown={startResize(direction)}
            />
          ),
        )}
      </section>
    </div>
  )
}
