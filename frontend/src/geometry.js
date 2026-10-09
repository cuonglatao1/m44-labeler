// Same conventions as backend/m44/geometry.py: LiDAR frame, bottom-center boxes, size = [l, w, h].
export const EDGES = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]]

export function boxCorners({ center, size, yaw }) {
  const [l, w, h] = size
  const xs = [1, 1, -1, -1, 1, 1, -1, -1].map((v) => (v * l) / 2)
  const ys = [1, -1, -1, 1, 1, -1, -1, 1].map((v) => (v * w) / 2)
  const zs = [0, 0, 0, 0, 1, 1, 1, 1].map((v) => v * h)
  const c = Math.cos(yaw), s = Math.sin(yaw)
  return xs.map((x, k) => [c * x - s * ys[k] + center[0], s * x + c * ys[k] + center[1], zs[k] + center[2]])
}

export const COLORS = {
  ok: '#34d399', flagged: '#f87171', unchecked: '#8b93a7', det: '#e2e8f0', missing: '#f59e0b', selected: '#ffffff',
}

// one hue per class, kept away from the status colours (red = flag, amber = missing)
export const CLASS_COLORS = {
  car: '#4f8cff', truck: '#8b7bff', bus: '#c084fc', trailer: '#e879f9', construction_vehicle: '#facc15',
  pedestrian: '#2dd4bf', motorcycle: '#fb923c', bicycle: '#a3e635', traffic_cone: '#fdba74', barrier: '#94a3b8',
}

// colour of a cuboid: by class (flagged ones red when the checker runs) or by check status
export function boxColor(box, status, colorBy, selected) {
  if (box.box_id === selected) return COLORS.selected
  if (colorBy === 'status') return COLORS[status[box.box_id] || 'unchecked']
  if (status[box.box_id] === 'flagged') return COLORS.flagged
  return CLASS_COLORS[box.cls] || COLORS.unchecked
}

// The check with the reviewer's verdicts applied: flags marked false alarm (✗) are dropped, and a source whose every
// flag on a cuboid was dismissed counts as checked and fine; the QC level is recomputed from what is left.
export function applyVerdicts(check, dismissed) {
  const active = check.flags.filter((f) => !dismissed(f))
  const flaggedBy = {}
  for (const f of active) if (f.box_id) (flaggedBy[f.box_id] ||= new Set()).add(f.source || 'camera')
  const qc = {}
  for (const [id, q] of Object.entries(check.qc || {})) {
    const st = {}
    for (const s of ['camera', 'lidar', 'track']) {
      st[s] = flaggedBy[id]?.has(s) ? 'flagged' : q[s] === 'flagged' ? 'ok' : q[s]
    }
    const nOk = Object.values(st).filter((v) => v === 'ok').length
    const level = Object.values(st).includes('flagged') ? 'flagged' : nOk >= 2 ? 'high' : nOk ? 'medium' : 'none'
    qc[id] = { ...q, ...st, level }
  }
  return { ...check, flags: active, qc }
}

// box_id -> 'flagged' | 'ok' | 'unchecked': any flag (camera, LiDAR or temporal) = flagged; verified by at least one
// source = ok (qc levels high / medium)
export function boxStatus(check) {
  const status = {}
  for (const m of check.matches) status[m.box_id] = 'ok'
  for (const [id, q] of Object.entries(check.qc || {})) if (q.level === 'high' || q.level === 'medium') status[id] = 'ok'
  for (const f of check.flags) if (f.box_id) status[f.box_id] = 'flagged'
  return status
}

function toCam(p, M) {
  return [0, 1, 2].map((r) => M[r][0] * p[0] + M[r][1] * p[1] + M[r][2] * p[2] + M[r][3])
}

function toImg(p, K) {
  const u = K[0][0] * p[0] + K[0][1] * p[1] + K[0][2] * p[2]
  const v = K[1][0] * p[0] + K[1][1] * p[1] + K[1][2] * p[2]
  const w = K[2][0] * p[0] + K[2][1] * p[1] + K[2][2] * p[2]
  return [u / w, v / w]
}

// Port of project_box (backend/m44/geometry.py) for live drawing while editing: clipped 2D bbox + corners
// (null for corners behind the camera). The flags still come from the backend check.
export function projectBox(box, cam, W = 1600, H = 900, near = 0.1) {
  const pc = boxCorners(box).map((p) => toCam(p, cam.lidar2cam))
  const front = pc.map((p) => p[2] > near)
  if (!front.some(Boolean)) return null
  const pts = pc.filter((_, i) => front[i])
  for (const [a, b] of EDGES) {
    if (front[a] !== front[b]) {
      const t = (near - pc[a][2]) / (pc[b][2] - pc[a][2])
      pts.push(pc[a].map((v, k) => v + t * (pc[b][k] - v)))
    }
  }
  const uv = pts.map((p) => toImg(p, cam.cam2img))
  const x1 = Math.max(Math.min(...uv.map((q) => q[0])), 0), x2 = Math.min(Math.max(...uv.map((q) => q[0])), W)
  const y1 = Math.max(Math.min(...uv.map((q) => q[1])), 0), y2 = Math.min(Math.max(...uv.map((q) => q[1])), H)
  if (x2 - x1 < 1 || y2 - y1 < 1) return null
  return { box_id: box.box_id, bbox: [x1, y1, x2, y2], corners_2d: pc.map((p, i) => (front[i] ? toImg(p, cam.cam2img) : null)) }
}

// Point where the ray through image pixel (u, v) of camera `cam` meets the horizontal plane z = zPlane (LiDAR frame),
// or null when the ray points away from it (above the horizon) or hits it more than maxDist m away.
export function pixelToPlane(cam, u, v, zPlane, maxDist = 80) {
  const K = cam.cam2img, M = cam.lidar2cam
  const dc = [(u - K[0][2] - K[0][1] * (v - K[1][2]) / K[1][1]) / K[0][0], (v - K[1][2]) / K[1][1], 1]
  // camera -> LiDAR: R^T, origin = -R^T t
  const R = [0, 1, 2].map((r) => [M[r][0], M[r][1], M[r][2]])
  const t = [M[0][3], M[1][3], M[2][3]]
  const o = [0, 1, 2].map((k) => -(R[0][k] * t[0] + R[1][k] * t[1] + R[2][k] * t[2]))
  const d = [0, 1, 2].map((k) => R[0][k] * dc[0] + R[1][k] * dc[1] + R[2][k] * dc[2])
  if (Math.abs(d[2]) < 1e-6) return null
  const s = (zPlane - o[2]) / d[2]
  if (s <= 0) return null
  const p = [o[0] + s * d[0], o[1] + s * d[1], zPlane]
  return Math.hypot(p[0] - o[0], p[1] - o[1]) > maxDist ? null : p
}

// typical nuScenes sizes [l, w, h] in m, used for new cuboids
export const CLASS_SIZES = {
  car: [4.6, 1.9, 1.7], truck: [7.0, 2.5, 3.0], bus: [11.0, 2.9, 3.5], trailer: [10.0, 2.6, 3.8],
  construction_vehicle: [6.5, 2.8, 3.2], pedestrian: [0.7, 0.7, 1.75], motorcycle: [2.1, 0.8, 1.5],
  bicycle: [1.7, 0.6, 1.3], traffic_cone: [0.4, 0.4, 1.0], barrier: [0.5, 2.5, 1.0],
}
export const CLASSES = Object.keys(CLASS_SIZES)

const LIDAR_HEIGHT = 1.84 // nuScenes LIDAR_TOP above the ground, fallback when there are no points around

// ground z near (x, y): low percentile of the LiDAR points within 1.5 m
export function groundZ(points, x, y) {
  if (!points) return -LIDAR_HEIGHT
  const zs = []
  for (let k = 0; k < points.length; k += 4) {
    const dx = points[k] - x, dy = points[k + 1] - y
    if (dx * dx + dy * dy < 2.25) zs.push(points[k + 2])
  }
  if (zs.length < 10) return -LIDAR_HEIGHT
  zs.sort((a, b) => a - b)
  return zs[Math.floor(zs.length * 0.05)]
}

// move one face of the box to local coordinate q along axis 0 (length) or 1 (width), keeping the
// opposite face fixed; sign = +1 for the front/left face, -1 for the back/right face
export function resizeFace(box, axis, sign, q) {
  const half = box.size[axis] / 2
  const fixed = -sign * half
  const size = Math.max(0.2, sign * (q - fixed))
  const mid = fixed + (sign * size) / 2
  const c = Math.cos(box.yaw), s = Math.sin(box.yaw)
  const dir = axis === 0 ? [c, s] : [-s, c]
  const newSize = [...box.size]
  newSize[axis] = size
  return { ...box, size: newSize, center: [box.center[0] + dir[0] * mid, box.center[1] + dir[1] * mid, box.center[2]] }
}

// world (x, y) -> box-local (forward, left)
export function toLocal(box, x, y) {
  const c = Math.cos(box.yaw), s = Math.sin(box.yaw)
  const dx = x - box.center[0], dy = y - box.center[1]
  return [c * dx + s * dy, -s * dx + c * dy]
}

// height colormap shared by the BEV and the side views: deep blue (ground) -> cyan -> green -> amber -> rose (high)
const HEIGHT_STOPS = [[0.17, 0.35, 1.0], [0.13, 0.83, 0.93], [0.2, 0.83, 0.6], [0.98, 0.8, 0.08], [0.98, 0.44, 0.52]]
export function heightColor(z, zMin = -2, zMax = 2.5) {
  const t = Math.min(Math.max((z - zMin) / (zMax - zMin), 0), 1) * (HEIGHT_STOPS.length - 1)
  const i = Math.min(Math.floor(t), HEIGHT_STOPS.length - 2), f = t - i
  const a = HEIGHT_STOPS[i], b = HEIGHT_STOPS[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}
