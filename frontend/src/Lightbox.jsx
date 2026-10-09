import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Maximize, Minus, Plus, X } from 'lucide-react'
import CameraView from './CameraView.jsx'

const MIN_SCALE = 1, MAX_SCALE = 8
const DRAG_PX = 4 // pointer moved more than this = pan, the click that follows is swallowed

// Full-screen camera viewer: wheel to zoom at the cursor, drag to pan, double-click to reset,
// ← / → to switch camera, Esc to close. Cuboids and amber boxes stay clickable (select / propose).
export default function Lightbox({ cams, cam, setCam, onClose, cameraProps }) {
  const [view, setView] = useState({ s: 1, x: 0, y: 0 })
  const stage = useRef(null)
  const drag = useRef(null)
  const moved = useRef(false)

  useEffect(() => { setView({ s: 1, x: 0, y: 0 }) }, [cam])

  const step = useCallback((d) => setCam(cams[(cams.indexOf(cam) + d + cams.length) % cams.length]), [cam, cams, setCam])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') step(1)
      else if (e.key === 'ArrowLeft') step(-1)
      else return
      e.stopImmediatePropagation(); e.preventDefault()
    }
    window.addEventListener('keydown', onKey, true) // capture: wins over the app shortcuts (← → change frame)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose, step])

  // zoom keeping the point under the cursor fixed
  const zoomAt = useCallback((factor, cx, cy) => {
    setView((v) => {
      const s = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.s * factor))
      if (s === MIN_SCALE) return { s, x: 0, y: 0 }
      const k = s / v.s
      return { s, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k }
    })
  }, [])

  const onWheel = (e) => {
    const r = stage.current.getBoundingClientRect()
    zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2)
  }

  const zoomButton = (f) => zoomAt(f, 0, 0)

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lb-head" onClick={(e) => e.stopPropagation()}>
        <b>{cam.replace('CAM_', '').replace('_', ' ')}</b>
        <div className="lb-cams">
          {cams.map((c) => (
            <button key={c} className={`seg-btn ${c === cam ? 'on' : ''}`} onClick={() => setCam(c)}>
              {c.replace('CAM_', '').replace('_', ' ')}
            </button>
          ))}
        </div>
        <span className="grow" />
        <span className="lb-hint">lăn chuột: zoom · kéo ảnh: di chuyển · kéo cuboid đang chọn: dời nó · bấm đúp: vừa khung · <kbd>←</kbd><kbd>→</kbd> đổi camera</span>
        <button className="icon-btn" onClick={() => zoomButton(1 / 1.5)} title="Thu nhỏ"><Minus size={16} /></button>
        <span className="lb-zoom">{Math.round(view.s * 100)}%</span>
        <button className="icon-btn" onClick={() => zoomButton(1.5)} title="Phóng to"><Plus size={16} /></button>
        <button className="icon-btn" onClick={() => setView({ s: 1, x: 0, y: 0 })} title="Vừa khung"><Maximize size={16} /></button>
        <button className="icon-btn" onClick={onClose} title="Đóng (Esc)"><X size={18} /></button>
      </div>
      <button className="lb-nav left" onClick={(e) => { e.stopPropagation(); step(-1) }} aria-label="Camera trước"><ChevronLeft size={28} /></button>
      <button className="lb-nav right" onClick={(e) => { e.stopPropagation(); step(1) }} aria-label="Camera sau"><ChevronRight size={28} /></button>
      <div ref={stage} className="lb-stage" onClick={(e) => e.stopPropagation()} onWheel={onWheel}
        onDoubleClick={() => setView({ s: 1, x: 0, y: 0 })}
        onPointerDown={(e) => {
          if (e.button !== 0) return
          drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
          moved.current = false
        }}
        onPointerMove={(e) => {
          const d = drag.current
          if (!d) return
          const dx = e.clientX - d.x, dy = e.clientY - d.y
          if (!moved.current && Math.hypot(dx, dy) < DRAG_PX) return
          moved.current = true
          if (view.s > 1) setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }))
        }}
        onPointerUp={() => { drag.current = null }}
        onClickCapture={(e) => { if (moved.current) { e.stopPropagation(); moved.current = false } }}>
        <div className="lb-image" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, cursor: view.s > 1 ? 'grab' : 'default' }}>
          <CameraView cam={cam} zoom={view.s} {...cameraProps} />
        </div>
      </div>
    </div>
  )
}
