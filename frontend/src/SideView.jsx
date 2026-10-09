import { useEffect, useRef, useState } from 'react'
import { boxCorners, heightColor, resizeFace, toLocal } from './geometry.js'

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

// ---------- top view of the selected cuboid ----------
// Looking down, turned with the cuboid: front to the right, its left side up. Drag the body to move it on the ground,
// an edge to move that face, the round handle in front of it to turn it. Only points between 15 cm above the cuboid
// bottom and its top are drawn (the ground would hide the object).
function makeTop(box) {
  const [l, w] = box.size
  const scale = Math.min(W / (l + 2 * MARGIN_ALONG), H / (w + 2 * MARGIN_ALONG))
  return {
    box, scale,
    toScreen: (u, v) => [W / 2 + u * scale, H / 2 - v * scale],
    fromScreen: (x, y) => [(x - W / 2) / scale, (H / 2 - y) / scale],
  }
}

export function TopView({ box, points, onDragStart, onChange }) {
  const canvas = useRef()
  const drag = useRef(null)
  const [, rerender] = useState(0)
  const v = drag.current?.view ?? makeTop(box)

  useEffect(() => {
    const ctx = canvas.current.getContext('2d')
    ctx.clearRect(0, 0, W, H)
    if (!points) return
    const b = v.box
    const [l, w, h] = b.size
    for (let k = 0; k < points.length; k += 4) {
      const dz = points[k + 2] - b.center[2]
      if (dz < 0.15 || dz > h + 0.4) continue
      const [u, s] = toLocal(b, points[k], points[k + 1])
      if (Math.abs(u) > l / 2 + MARGIN_ALONG || Math.abs(s) > w / 2 + MARGIN_ALONG) continue
      const [r, g, bl] = heightColor(dz, -0.3, h + 0.3)
      ctx.fillStyle = `rgb(${r * 255 | 0},${g * 255 | 0},${bl * 255 | 0})`
      const [sx, sy] = v.toScreen(u, s)
      ctx.fillRect(sx - 1, sy - 1, 2.2, 2.2)
    }
  })

  const local = (e) => {
    const svg = e.currentTarget.ownerSVGElement ?? e.currentTarget
    const r = svg.getBoundingClientRect()
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
      const [u, s] = local(e)
      const b = d.start
      if (d.kind === 'body') {
        const du = u - d.grab[0], ds = s - d.grab[1]
        const c = Math.cos(b.yaw), sn = Math.sin(b.yaw)
        onChange({ ...b, center: [b.center[0] + c * du - sn * ds, b.center[1] + sn * du + c * ds, b.center[2]] })
      } else if (d.kind === 'rotate') {
        const turn = Math.atan2(s, u) - Math.atan2(d.grab[1], d.grab[0])
        onChange({ ...b, yaw: b.yaw + turn })
      } else {
        const [axis, sign, q] = { front: [0, 1, u], back: [0, -1, u], left: [1, 1, s], right: [1, -1, s] }[d.kind]
        onChange(resizeFace(b, axis, sign, q))
      }
    },
    onPointerUp: (e) => {
      if (!drag.current) return
      e.currentTarget.releasePointerCapture(e.pointerId)
      drag.current = null
      rerender((n) => n + 1)
    },
  })

  // the current cuboid in the (frozen while dragging) frame of the view
  const cur = drag.current ? box : v.box
  const pts = boxCorners(cur).slice(0, 4).map(([x, y]) => v.toScreen(...toLocal(v.box, x, y)))
  // bottom corners (geometry.js boxCorners): 0 front-left, 1 front-right, 2 back-right, 3 back-left
  const [p0, p1, p2, p3] = pts
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  const front = mid(p0, p1)
  const centre = mid(p0, p2)
  const dir = [front[0] - centre[0], front[1] - centre[1]]
  const len = Math.hypot(...dir) || 1
  const knob = [front[0] + (dir[0] / len) * 16, front[1] + (dir[1] / len) * 16]
  const edge = { stroke: 'transparent', strokeWidth: 12 }
  const line = (a, b, kind, cursor) => (
    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} {...edge} style={{ cursor }} {...handlers(kind)} />
  )

  return (
    <div className="sideview">
      <canvas ref={canvas} width={W} height={H} />
      <svg viewBox={`0 0 ${W} ${H}`}>
        <polygon points={pts.map((p) => p.join(',')).join(' ')} fill="#ffffff14" stroke="#ffffff" strokeWidth={1.5}
          style={{ cursor: 'move' }} {...handlers('body')} />
        <line x1={p0[0]} y1={p0[1]} x2={p1[0]} y2={p1[1]} stroke="#4f8cff" strokeWidth={2.5} pointerEvents="none" />
        {line(p0, p1, 'front', 'ew-resize')}
        {line(p2, p3, 'back', 'ew-resize')}
        {line(p1, p2, 'right', 'ns-resize')}
        {line(p3, p0, 'left', 'ns-resize')}
        <line x1={front[0]} y1={front[1]} x2={knob[0]} y2={knob[1]} stroke="#4f8cff" strokeWidth={1.5} pointerEvents="none" />
        <circle cx={knob[0]} cy={knob[1]} r={6} fill="#4f8cff" stroke="#ffffff" strokeWidth={1.5}
          style={{ cursor: 'grab' }} {...handlers('rotate')}><title>Kéo để xoay</title></circle>
      </svg>
    </div>
  )
}
