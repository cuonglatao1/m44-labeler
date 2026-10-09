import { useRef } from 'react'
import { api } from './api.js'
import { COLORS, EDGES, pixelToPlane } from './geometry.js'

const W = 1600, H = 900

// One camera image with the cuboids projected in the browser (they follow edits live), YOLO boxes and the
// MISSING_3D boxes of the last check. Click an amber box or Shift+click a YOLO box -> onPropose(cam, bbox, cls).
// `thumb`: small preview, not interactive (the parent makes it a button that focuses this camera).
// `onBackground`: click on the image away from any cuboid (opens the full-screen viewer); `zoom`: CSS zoom of
// the image, strokes are divided by it so lines stay thin when zoomed in.
// Dragging the selected cuboid (when `box`, `cal` and onBoxChange are given) moves it on the ground: the pixel under the
// mouse is followed on the horizontal plane through the middle of the cuboid, so it slides under the cursor.
const DRAG_PX = 3

export default function CameraView({ frameIndex, cam, proj, flags, dets, colors, selected, onSelect, onPropose, thumb, label,
  onBackground, zoom = 1, ghost, box, cal, onDragStart, onBoxChange }) {
  const drag = useRef(null)
  const canDrag = !thumb && box && cal && onBoxChange
  const imgPoint = (e) => {
    const r = e.currentTarget.ownerSVGElement.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H]
  }
  const dragHandlers = canDrag ? {
    onPointerDown: (e) => {
      if (e.button !== 0) return
      e.stopPropagation() // the full-screen viewer would pan
      const zMid = box.center[2] + box.size[2] / 2
      const hit = pixelToPlane(cal, ...imgPoint(e), zMid)
      if (!hit) return
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current = { start: box, hit, zMid, x: e.clientX, y: e.clientY, moving: false }
    },
    onPointerMove: (e) => {
      const d = drag.current
      if (!d) return
      if (!d.moving) {
        if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < DRAG_PX) return
        d.moving = true
        onDragStart?.()
      }
      const p = pixelToPlane(cal, ...imgPoint(e), d.zMid)
      if (!p) return
      const b = d.start
      onBoxChange({ ...b, center: [b.center[0] + p[0] - d.hit[0], b.center[1] + p[1] - d.hit[1], b.center[2]] })
    },
    onPointerUp: (e) => {
      const d = drag.current
      if (!d) return
      e.currentTarget.releasePointerCapture(e.pointerId)
      drag.current = null
      if (d.moving) e.currentTarget.dataset.dragged = '1' // the click that follows is not a selection
    },
  } : {}
  const camDets = dets.filter((d) => d.cam === cam)
  const missing = flags.filter((f) => f.cam === cam && f.type === 'MISSING_3D')
  const nFlags = flags.filter((f) => f.cam === cam).length
  const sel = proj.find((p) => p.box_id === selected)
  const k = thumb ? 2.2 : 1 / zoom // thicker strokes when the image is shown small, thinner when zoomed in

  return (
    <div className="cam">
      <img src={api.imageUrl(frameIndex, cam)} alt={cam} draggable={false} />
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
        style={thumb ? { pointerEvents: 'none' } : onBackground ? { cursor: 'zoom-in' } : undefined}
        onClick={(e) => { if (e.target === e.currentTarget) onBackground?.() }}>
        {camDets.map((d, i) => (
          <rect key={`d${i}`} x={d.bbox[0]} y={d.bbox[1]} width={d.bbox[2] - d.bbox[0]} height={d.bbox[3] - d.bbox[1]}
            fill="transparent" stroke={COLORS.det} strokeOpacity={0.55} strokeWidth={1.5 * k} strokeDasharray="7 6"
            onClick={(e) => { if (e.shiftKey) onPropose(cam, d.bbox, d.cls); else onBackground?.() }}>
            <title>{`YOLO ${d.cls} ${d.score.toFixed(2)} – Shift+bấm để gợi ý cuboid`}</title>
          </rect>
        ))}
        {proj.map((p) => {
          const on = p.box_id === selected
          return (
            <g key={p.box_id} style={{ cursor: on && canDrag ? 'move' : 'pointer', touchAction: 'none' }}
              onClick={(e) => {
                if (e.currentTarget.dataset.dragged) { delete e.currentTarget.dataset.dragged; return }
                onSelect(p.box_id)
              }}
              {...(on ? dragHandlers : {})}>
              {EDGES.map(([a, b], i) => {
                const A = p.corners_2d[a], B = p.corners_2d[b]
                if (!A || !B) return null
                return <line key={i} x1={A[0]} y1={A[1]} x2={B[0]} y2={B[1]} stroke={colors[p.box_id]}
                  strokeWidth={(on ? 4 : 2.5) * k} strokeOpacity={on || !selected ? 1 : 0.75} />
              })}
              <rect x={p.bbox[0]} y={p.bbox[1]} width={p.bbox[2] - p.bbox[0]} height={p.bbox[3] - p.bbox[1]}
                fill="transparent" />
            </g>
          )
        })}
        {/* on top: a missing box must stay clickable even where a cuboid's bbox overlaps it */}
        {missing.map((f) => (
          <rect key={f.flag_id} x={f.det_bbox[0]} y={f.det_bbox[1]} width={f.det_bbox[2] - f.det_bbox[0]}
            height={f.det_bbox[3] - f.det_bbox[1]} rx={6} fill={COLORS.missing} fillOpacity={0.16}
            stroke={COLORS.missing} strokeWidth={3 * k} style={{ cursor: 'copy' }}
            onClick={() => onPropose(cam, f.det_bbox, f.cls_2d)}>
            <title>Thiếu cuboid – bấm để gợi ý</title>
          </rect>
        ))}
        {ghost && (
          <g pointerEvents="none">
            {EDGES.map(([a, b], i) => {
              const A = ghost.corners_2d[a], B = ghost.corners_2d[b]
              if (!A || !B) return null
              return <line key={i} x1={A[0]} y1={A[1]} x2={B[0]} y2={B[1]} stroke="#ffffff" strokeWidth={3 * k} strokeDasharray="12 8" />
            })}
          </g>
        )}
        {sel && label && (
          <g pointerEvents="none">
            <rect x={sel.bbox[0]} y={Math.max(sel.bbox[1] - 34, 0)} width={label.length * 15 + 20} height={30} rx={5} fill="#ffffff" />
            <text x={sel.bbox[0] + 10} y={Math.max(sel.bbox[1] - 34, 0) + 21} fontSize={20} fontWeight={600} fill="#0b0d12">{label}</text>
          </g>
        )}
      </svg>
      <span className="cam-name">
        {cam.replace('CAM_', '').replace('_', ' ')}
        {nFlags > 0 && <span className="cam-badge" title={`${nFlags} cờ`}>{nFlags}</span>}
      </span>
    </div>
  )
}
