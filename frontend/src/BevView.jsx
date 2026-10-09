import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls, OrthographicCamera } from '@react-three/drei'
import { EDGES, boxCorners, heightColor, resizeFace, toLocal } from './geometry.js'

const CLICK_PX = 4 // pointer moved more than this = pan, not a click

// LiDAR frame: x forward, y left, z up. Top-down camera with +x pointing up on screen (see TOP_OFFSET).
function Points({ points }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry()
    if (!points) return g
    const n = points.length / 4
    const pos = new THREE.InterleavedBufferAttribute(new THREE.InterleavedBuffer(points, 4), 3, 0)
    const col = new Float32Array(n * 3)
    for (let k = 0; k < n; k++) {
      const [r, g, b] = heightColor(points[k * 4 + 2])
      const lit = 0.55 + 0.45 * Math.min(points[k * 4 + 3] / 40, 1) // brighter for strong returns
      col[k * 3] = r * lit; col[k * 3 + 1] = g * lit; col[k * 3 + 2] = b * lit
    }
    g.setAttribute('position', pos)
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    return g
  }, [points])
  return (
    <points geometry={geom}>
      <pointsMaterial size={1.7} sizeAttenuation={false} vertexColors transparent opacity={0.92} />
    </points>
  )
}

function Cuboid({ box, color, selected, onSelect, dragHandlers }) {
  const { segs, arrow } = useMemo(() => {
    const cs = boxCorners(box)
    // heading arrow on the top face: tip on the front face, base a short way back
    const [l, w, h] = box.size
    const c = Math.cos(box.yaw), s = Math.sin(box.yaw)
    const at = (fx, fy) => [box.center[0] + c * fx - s * fy, box.center[1] + s * fx + c * fy, box.center[2] + h + 0.01]
    const back = Math.min(l * 0.35, 1.2)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(
      [...at(l / 2, 0), ...at(l / 2 - back, w * 0.32), ...at(l / 2 - back, -w * 0.32)], 3))
    return { segs: EDGES.flatMap(([a, b]) => [cs[a], cs[b]]), arrow: g }
  }, [box])
  const [l, w, h] = box.size
  return (
    <group>
      <Line points={segs} segments color={color} lineWidth={selected ? 2.6 : 1.6} transparent opacity={selected ? 1 : 0.92} />
      <mesh geometry={arrow}>
        <meshBasicMaterial color={color} side={THREE.DoubleSide} transparent opacity={0.9} />
      </mesh>
      {/* solid for clicking; the selected box is dragged by its body */}
      <mesh position={[box.center[0], box.center[1], box.center[2] + h / 2]} rotation={[0, 0, box.yaw]}
        onClick={(e) => { e.stopPropagation(); if (e.delta < CLICK_PX) onSelect(box.box_id) }}
        {...dragHandlers('move', box.box_id)}>
        <boxGeometry args={[l, w, h]} />
        <meshBasicMaterial color={color} transparent opacity={selected ? 0.2 : 0.07} depthWrite={false} />
      </mesh>
    </group>
  )
}

// constant on-screen size whatever the zoom
function Handle({ position, color, handlers }) {
  const ref = useRef()
  useFrame(({ camera }) => ref.current?.scale.setScalar(5.5 / camera.zoom))
  return (
    <group ref={ref} position={position}>
      <mesh renderOrder={10} {...handlers}>
        <circleGeometry args={[1, 24]} />
        <meshBasicMaterial color="#0b0d12" depthTest={false} />
      </mesh>
      <mesh renderOrder={11} position={[0, 0, 0.001]}>
        <ringGeometry args={[0.55, 1, 24]} />
        <meshBasicMaterial color={color} depthTest={false} />
      </mesh>
    </group>
  )
}

// The canvas can lag one React render behind the page, so handlers read live state through
// callbacks backed by refs in App (getBox, onGroundClick) instead of props captured at render time.
function useBoxDrag(getBox, onDragStart, onChange) {
  const controls = useThree((s) => s.controls)
  const drag = useRef(null)
  // onlyId: start only if that box is the selected one (body drag); handles belong to the selection anyway
  return (kind, onlyId) => ({
    onPointerDown: (e) => {
      const box = getBox()
      if (e.button !== 0 || !box || (onlyId && box.box_id !== onlyId)) return
      e.stopPropagation()
      e.target.setPointerCapture(e.pointerId)
      if (controls) controls.enabled = false
      const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -box.center[2])
      const grab = new THREE.Vector3()
      e.ray.intersectPlane(plane, grab)
      drag.current = { kind, start: box, plane, grab }
      onDragStart()
    },
    onPointerMove: (e) => {
      const d = drag.current
      if (!d) return
      e.stopPropagation()
      const p = new THREE.Vector3()
      if (!e.ray.intersectPlane(d.plane, p)) return
      const b = d.start
      if (d.kind === 'move') {
        onChange({ ...b, center: [b.center[0] + p.x - d.grab.x, b.center[1] + p.y - d.grab.y, b.center[2]] })
      } else if (d.kind === 'rotate') {
        onChange({ ...b, yaw: Math.atan2(p.y - b.center[1], p.x - b.center[0]) })
      } else {
        const [axis, sign] = { front: [0, 1], back: [0, -1], left: [1, 1], right: [1, -1] }[d.kind]
        onChange(resizeFace(b, axis, sign, toLocal(b, p.x, p.y)[axis]))
      }
    },
    onPointerUp: (e) => {
      if (!drag.current) return
      e.target.releasePointerCapture(e.pointerId)
      drag.current = null
      if (controls) controls.enabled = true
    },
  })
}

function SelectedHandles({ box, dragHandlers }) {
  const [l, w, h] = box.size
  const c = Math.cos(box.yaw), s = Math.sin(box.yaw)
  const z = box.center[2] + h
  const at = (fx, fy) => [box.center[0] + c * fx - s * fy, box.center[1] + s * fx + c * fy, z]
  return (
    <group>
      <Handle position={at(l / 2, 0)} color="#ffffff" handlers={dragHandlers('front')} />
      <Handle position={at(-l / 2, 0)} color="#ffffff" handlers={dragHandlers('back')} />
      <Handle position={at(0, w / 2)} color="#ffffff" handlers={dragHandlers('left')} />
      <Handle position={at(0, -w / 2)} color="#ffffff" handlers={dragHandlers('right')} />
      <Handle position={at(l / 2 + 1.2, 0)} color="#7c9dff" handlers={dragHandlers('rotate')} />
    </group>
  )
}

const FOCUS_S = 0.3 // seconds of the glide to a selected cuboid

// Glide the view to a point when focus.tick changes (selection, "C"): the orbit target and the camera move by
// the same offset, so a rotated 3D view keeps its angle; zoom only goes in (to at least focus.zoom).
function Focus({ focus }) {
  const controls = useThree((s) => s.controls)
  const camera = useThree((s) => s.camera)
  const anim = useRef(null)
  useEffect(() => {
    if (!focus || !controls) return
    anim.current = {
      from: controls.target.clone(), to: new THREE.Vector3(focus.at[0], focus.at[1], focus.at[2] ?? 0),
      fromZoom: camera.zoom, toZoom: Math.max(camera.zoom, focus.zoom ?? 18), t: 0,
    }
  }, [focus?.tick]) // eslint-disable-line react-hooks/exhaustive-deps
  useFrame((_, dt) => {
    const a = anim.current
    if (!a || !controls) return
    a.t = Math.min(1, a.t + dt / FOCUS_S)
    const ease = 1 - (1 - a.t) ** 3
    const target = a.from.clone().lerp(a.to, ease)
    camera.position.add(target.clone().sub(controls.target))
    controls.target.copy(target)
    camera.zoom = a.fromZoom + (a.toZoom - a.fromZoom) * ease
    camera.updateProjectionMatrix()
    controls.update()
    if (a.t >= 1) anim.current = null
  })
  return null
}

const RINGS = [10, 20, 30, 40, 50] // m

// distance rings on the ground around the ego car (every 10 m, the 50 m ring a bit brighter) + faint axes
function RangeRings() {
  const rings = useMemo(() => RINGS.map((r) => {
    const pts = []
    for (let k = 0; k <= 128; k++) { const a = (k / 128) * Math.PI * 2; pts.push([r * Math.cos(a), r * Math.sin(a), -1.84]) }
    return pts
  }), [])
  return (
    <group>
      {rings.map((pts, i) => (
        <Line key={RINGS[i]} points={pts} color={RINGS[i] % 50 ? '#3a4560' : '#56658a'} lineWidth={1} transparent opacity={0.55} />
      ))}
      <Line points={[[-55, 0, -1.84], [55, 0, -1.84]]} color="#2c3448" lineWidth={1} transparent opacity={0.5} />
      <Line points={[[0, -55, -1.84], [0, 55, -1.84]]} color="#2c3448" lineWidth={1} transparent opacity={0.5} />
    </group>
  )
}

// the ego car: rounded body with a heading chevron (x forward)
function EgoCar() {
  const { body, chevron } = useMemo(() => {
    const L = 4.6, W = 1.9, R = 0.45
    const sh = new THREE.Shape()
    sh.moveTo(-L / 2 + R, -W / 2)
    sh.lineTo(L / 2 - R, -W / 2); sh.quadraticCurveTo(L / 2, -W / 2, L / 2, -W / 2 + R)
    sh.lineTo(L / 2, W / 2 - R); sh.quadraticCurveTo(L / 2, W / 2, L / 2 - R, W / 2)
    sh.lineTo(-L / 2 + R, W / 2); sh.quadraticCurveTo(-L / 2, W / 2, -L / 2, W / 2 - R)
    sh.lineTo(-L / 2, -W / 2 + R); sh.quadraticCurveTo(-L / 2, -W / 2, -L / 2 + R, -W / 2)
    const ch = new THREE.Shape()
    ch.moveTo(1.6, 0); ch.lineTo(0.5, 0.6); ch.lineTo(0.5, -0.6); ch.lineTo(1.6, 0)
    return { body: new THREE.ShapeGeometry(sh, 6), chevron: new THREE.ShapeGeometry(ch) }
  }, [])
  return (
    <group position={[0, 0, 0]}>
      <mesh geometry={body}><meshBasicMaterial color="#2a3550" /></mesh>
      <mesh geometry={chevron} position={[0, 0, 0.01]}><meshBasicMaterial color="#8fb0ff" /></mesh>
    </group>
  )
}

// preview of a suggested fix: dashed white outline, not interactive
function GhostCuboid({ box }) {
  const segs = useMemo(() => { const cs = boxCorners(box); return EDGES.flatMap(([a, b]) => [cs[a], cs[b]]) }, [box])
  return <Line points={segs} segments dashed dashSize={0.35} gapSize={0.22} color="#ffffff" lineWidth={2.2} />
}

// LiDAR shots that went straight through the selected cuboid (where they leave it): evidence of an empty / too big box
function PassShots({ xy, z }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(xy.flatMap(([x, y]) => [x, y, z]), 3))
    return g
  }, [xy, z])
  return (
    <points geometry={geom} renderOrder={3}>
      <pointsMaterial size={6} sizeAttenuation={false} color="#fb7185" transparent opacity={0.95} depthTest={false} />
    </points>
  )
}

function Scene({ points, boxes, colorOf, selected, onSelect, onGroundClick, getSelected, onDragStart, onBoxChange, focus, ghost,
  passXY }) {
  const sel = boxes.find((b) => b.box_id === selected)
  const dragHandlers = useBoxDrag(getSelected, onDragStart, onBoxChange)
  return (
    <>
      <Points points={points} />
      <Focus focus={focus} />
      <RangeRings />
      {/* ground catcher: click = add a cuboid (add mode) or deselect */}
      <mesh position={[0, 0, -1.84]} onClick={(e) => { if (e.delta < CLICK_PX) onGroundClick(e.point.x, e.point.y) }}>
        <planeGeometry args={[400, 400]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      <EgoCar />
      {boxes.map((b) => (
        <Cuboid key={b.box_id} box={b} selected={b.box_id === selected} onSelect={onSelect} dragHandlers={dragHandlers}
          color={colorOf(b)} />
      ))}
      {sel && <SelectedHandles box={sel} dragHandlers={dragHandlers} />}
      {ghost && <GhostCuboid box={ghost} />}
      {sel && passXY?.length > 0 && <PassShots xy={passXY} z={sel.center[2] + sel.size[2] + 0.05} />}
    </>
  )
}

// Camera above the orbit target, a hair behind it on x: z is the orbit axis (drag left/right turns around the
// car, up/down tilts) and the tiny offset makes +x (forward) point up on screen in the top-down view.
const TOP_OFFSET = [-0.01, 0, 100]

// leaving 3D mode snaps back to the straight top-down view over the current target
function TopDown({ mode3d }) {
  const controls = useThree((s) => s.controls)
  const camera = useThree((s) => s.camera)
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (mode3d || !controls) return
    const t = controls.target
    camera.position.set(t.x + TOP_OFFSET[0], t.y + TOP_OFFSET[1], t.z + TOP_OFFSET[2])
    controls.update()
  }, [mode3d]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function BevView({ mode3d, addMode, ...props }) {
  return (
    <Canvas style={{ cursor: addMode ? 'crosshair' : 'default' }} gl={{ alpha: true, antialias: true }}>
      {/* transparent: the viewport card's radial gradient shows through */}
      <OrthographicCamera makeDefault position={TOP_OFFSET} up={[0, 0, 1]} zoom={8} near={0.1} far={1000} />
      {/* no damping: inertia keeps the view drifting after the mouse is released, which fights precise
          placement, the glide to a selection and the snap back to top-down */}
      <OrbitControls enableRotate={mode3d} enableDamping={false} maxPolarAngle={Math.PI / 2 - 0.05} screenSpacePanning makeDefault />
      <TopDown mode3d={mode3d} />
      <Scene {...props} />
    </Canvas>
  )
}
