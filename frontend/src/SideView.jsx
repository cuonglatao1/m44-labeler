import { useEffect, useRef, useState } from 'react'
import { heightColor, toLocal } from './geometry.js'

const W = 300, H = 170
const MARGIN_ALONG = 1.5 // m shown beyond the box on each side
const SLAB = 0.3         // m of points kept beyond the box across the view direction

// view = 'side' (looking from the right of the box, front to the right) or 'back' (looking from behind, left to the left)
function makeView(box, view) {
  const [l, w, h] = box.size
  const along = view === 'side' ? l : w
  const scale = Math.min(W / (along + 2 * MARGIN_ALONG), H / (h + 2))
  return {
    box, view, along, scale,
    toScreen: (u, z) => [W / 2 + u * scale, H / 2 - (z - h / 2) * scale],
    fromScreen: (x, y) => [(x - W / 2) / scale, (H / 2 - y) / scale + h / 2],
  }
}

// box-local (u, z) of a world point for this view; null if outside the slab
function project(view, x, y, z) {
  const b = view.box
  const [fx, fy] = toLocal(b, x, y)
  const [u, across, halfAcross] = view.view === 'side' ? [fx, fy, b.size[1] / 2] : [-fy, fx, b.size[0] / 2]
  if (Math.abs(across) > halfAcross + SLAB || Math.abs(u) > view.along / 2 + MARGIN_ALONG) return null
  return [u, z - b.center[2]]
}

export default function SideView({ box, points, view: viewName, onDragStart, onChange }) {
  const canvas = useRef()
  const drag = useRef(null)
  const [, rerender] = useState(0)
  // keep the view of the box as it was when the drag started, so the picture does not rescale under the mouse
  const v = drag.current?.view ?? makeView(box, viewName)

  useEffect(() => {
    const ctx = canvas.current.getContext('2d')
    ctx.clearRect(0, 0, W, H)
    // ground line of the box
    const [, gy] = v.toScreen(0, v.box.center[2] - v.box.center[2])
    ctx.fillStyle = 'rgba(255,255,255,0.06)'
    ctx.fillRect(0, gy, W, 1)
    if (!points) return
    const h = v.box.size[2]
    for (let k = 0; k < points.length; k += 4) {
      const p = project(v, points[k], points[k + 1], points[k + 2])
      if (!p) continue
      const [r, g, b] = heightColor(p[1], -0.3, h + 0.3)
      ctx.fillStyle = `rgb(${r * 255 | 0},${g * 255 | 0},${b * 255 | 0})`
      const [sx, sy] = v.toScreen(p[0], p[1])
      ctx.fillRect(sx - 1, sy - 1, 2.2, 2.2)
    }
  })

  const local = (e) => {
    const r = e.currentTarget.ownerSVGElement?.getBoundingClientRect() ?? e.currentTarget.getBoundingClientRect()
    return v.fromScreen(((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H)
  }

  const handlers = (kind) => ({
    onPointerDown: (e) => {
      e.stopPropagation()
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current = { kind, view: v, start: box, grab: local(e) }
      onDragStart()
    },
    onPointerMove: (e) => {
      const d = drag.current
      if (!d) return
      const [u, z] = local(e)
      const b = d.start
      const [l, w, h] = b.size
      if (d.kind === 'body') {
        onChange({ ...b, center: [b.center[0], b.center[1], b.center[2] + z - d.grab[1]] })
      } else if (d.kind === 'top') {
        onChange({ ...b, size: [l, w, Math.max(0.2, z)] })
      } else if (d.kind === 'bottom') {
        const bottom = Math.min(z, h - 0.2)
        onChange({ ...b, size: [l, w, h - bottom], center: [b.center[0], b.center[1], b.center[2] + bottom] })
      } else {
        // left / right face along u; u = forward (side view) or -left (back view)
        const sign = d.kind === 'right' ? 1 : -1
        const fixed = -sign * d.view.along / 2
        const size = Math.max(0.2, sign * (u - fixed))
        const mid = fixed + (sign * size) / 2
        const c = Math.cos(b.yaw), s = Math.sin(b.yaw)
        const [dir, axis] = d.view.view === 'side' ? [[c, s], 0] : [[s, -c], 1] // -left = right direction
        const newSize = [...b.size]
        newSize[axis] = size
        onChange({ ...b, size: newSize, center: [b.center[0] + dir[0] * mid, b.center[1] + dir[1] * mid, b.center[2]] })
      }
    },
    onPointerUp: (e) => {
      if (!drag.current) return
      e.currentTarget.releasePointerCapture(e.pointerId)
      drag.current = null
      rerender((n) => n + 1) // fresh view of the edited box
    },
  })

  // current box drawn in the (possibly frozen) view frame
  const cur = drag.current ? box : v.box
  const [fx, fy] = toLocal(v.box, cur.center[0], cur.center[1])
  const uMid = v.view === 'side' ? fx : -fy
  const along = v.view === 'side' ? cur.size[0] : cur.size[1]
  const z0 = cur.center[2] - v.box.center[2]
  const [x1, y2] = v.toScreen(uMid - along / 2, z0)
  const [x2, y1] = v.toScreen(uMid + along / 2, z0 + cur.size[2])
  const edge = { stroke: 'transparent', strokeWidth: 12 }

  return (
    <div className="sideview">
      <canvas ref={canvas} width={W} height={H} />
      <svg viewBox={`0 0 ${W} ${H}`}>
        <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="#ffffff14" stroke="#ffffff" strokeWidth={1.5}
          style={{ cursor: 'ns-resize' }} {...handlers('body')} />
        {v.view === 'side' && <line x1={x2} y1={y1} x2={x2} y2={y2} stroke="#4f8cff" strokeWidth={2.5} />}
        <line x1={x1} y1={y1} x2={x2} y2={y1} {...edge} style={{ cursor: 'ns-resize' }} {...handlers('top')} />
        <line x1={x1} y1={y2} x2={x2} y2={y2} {...edge} style={{ cursor: 'ns-resize' }} {...handlers('bottom')} />
        <line x1={x1} y1={y1} x2={x1} y2={y2} {...edge} style={{ cursor: 'ew-resize' }} {...handlers('left')} />
        <line x1={x2} y1={y1} x2={x2} y2={y2} {...edge} style={{ cursor: 'ew-resize' }} {...handlers('right')} />
      </svg>
    </div>
  )
}
