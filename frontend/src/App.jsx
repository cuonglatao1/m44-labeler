import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BoxSelect, Boxes, ChevronLeft, ChevronRight, CircleHelp, CopyPlus, Crosshair, Download, FileJson, Layers, Loader2,
  PanelLeftClose, PanelLeftOpen,
  Bot, Maximize2, MousePointer2, MoreHorizontal, Moon, Redo2, RotateCcw, Rotate3d, Save, Send, Sparkles, Trash2, TriangleAlert,
  Undo2, UserRound,
} from 'lucide-react'
import { api, chatStream, config as fetchConfig, resetChat, suggestFix } from './api.js'
import { CLASSES, CLASS_COLORS, CLASS_SIZES, COLORS, applyVerdicts, boxColor, boxStatus, groundZ, projectBox } from './geometry.js'
import BevView from './BevView.jsx'
import CameraView from './CameraView.jsx'
import SideView, { TopView } from './SideView.jsx'
import Lightbox from './Lightbox.jsx'
import { AssistantPanel } from './assistant.jsx'
import { Menu, PilotClock, ShortcutsDialog, Splitter, Toasts, Tool } from './chrome.jsx'
import { FrameSummary, Inspector, IssuesPanel, ObjectsPanel, PilotResult, flagKey } from './panels.jsx'

// nuScenes rig layout: front row left->right, back row as seen from behind the car
const CAM_GRID = ['CAM_FRONT_LEFT', 'CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_BACK_RIGHT', 'CAM_BACK', 'CAM_BACK_LEFT']
const CHECK_DEBOUNCE_MS = 150
const HISTORY_MAX = 200
const DEG = Math.PI / 180
const TOAST_MS = 4000

// Pilot mode (?pilot=<name>&frame=<index>&assist=0|1): one fixed frame that starts empty, no GT, a clock
// and a hand-in button; assist=0 hides everything the checker adds (flags, YOLO boxes, proposals).
const URL_PARAMS = new URLSearchParams(window.location.search)
const PILOT = URL_PARAMS.get('pilot') || null
const ASSIST = URL_PARAMS.get('assist') !== '0'
const PILOT_FRAME = Number(URL_PARAMS.get('frame') ?? 25)
const AUTOSAVE_MS = 3000
if (PILOT) api.setPilot(PILOT, ASSIST)

const loadPref = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const savePref = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

const bboxArea = (p) => (p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1])
const SPLIT_DEFAULT = 0.535, SPLIT_MIN = 0.25, SPLIT_MAX = 0.8   // share of the workspace taken by the BEV
const SIDE_DEFAULT = 356, SIDE_MIN = 280, SIDE_MAX = 720          // px, side panel
// object id that links a cuboid drawn here to the same object in other frames (GT cuboids keep the nuScenes token)
const newInstance = () => `obj_${Math.random().toString(16).slice(2, 12)}`
// the parts of a check response the UI keeps: camera + LiDAR + temporal flags, matches, QC per cuboid, coverage
const pickCheck = (r) => ({ flags: r.flags, matches: r.matches, qc: r.qc || {}, coverage: r.coverage || {} })

export default function App() {
  const [frames, setFrames] = useState([])
  const [index, setIndex] = useState(PILOT ? PILOT_FRAME : 0)
  const [frame, setFrame] = useState(null) // static part: cams, dets, meta
  const [boxes, setBoxes] = useState([])
  const [check, setCheck] = useState({ flags: [], matches: [], qc: {}, coverage: {} })
  const [checking, setChecking] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [points, setPoints] = useState(null)
  const [selected, setSelected] = useState(null)
  const [activeFlag, setActiveFlag] = useState(null)
  const [mode3d, setMode3d] = useState(false)
  const [addMode, setAddMode] = useState(false)
  const [newClass, setNewClass] = useState(() => loadPref('m44.newClass', 'car'))
  const [init, setInit] = useState(() => loadPref('m44.init', 'gt'))
  const [colorBy, setColorBy] = useState(() => loadPref('m44.colorBy', 'class'))
  const [tab, setTab] = useState(ASSIST ? 'issues' : 'objects')
  // assistant: chat thread, fix preview (dashed cuboid) and which suggestions were applied
  const [llm, setLlm] = useState({ available: false, model: '', reason: '' })
  const [demo, setDemo] = useState(false)
  const [chat, setChat] = useState([])
  const [chatBusy, setChatBusy] = useState(false)
  const [preview, setPreview] = useState(null)
  const [applied, setApplied] = useState(() => new Set())
  const chatSession = useRef(Math.random().toString(36).slice(2))
  const [focusCam, setFocusCam] = useState('CAM_FRONT')
  const [focus, setFocus] = useState(null) // {at: [x, y], tick} -> BEV re-centres
  const [savedAt, setSavedAt] = useState(null)
  const [feedback, setFeedback] = useState({}) // flagKey -> 'accept' | 'false_alarm'
  const [showDismissed, setShowDismissed] = useState(false)
  const [toasts, setToasts] = useState([])
  const [proposing, setProposing] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [lightbox, setLightbox] = useState(null) // camera shown full screen
  const [autoCenter, setAutoCenter] = useState(() => loadPref('m44.autoCenter', '1') === '1')
  // layout: collapsible tool rail, draggable split BEV | cameras and width of the side panel (remembered)
  const [railOpen, setRailOpen] = useState(() => loadPref('m44.railOpen', '1') === '1')
  const [split, setSplit] = useState(() => Number(loadPref('m44.split', SPLIT_DEFAULT)) || SPLIT_DEFAULT)
  const [sideW, setSideW] = useState(() => Number(loadPref('m44.sideW', SIDE_DEFAULT)) || SIDE_DEFAULT)
  const workRef = useRef(null)
  const toggleRail = useCallback(() => setRailOpen((o) => { savePref('m44.railOpen', o ? '0' : '1'); return !o }), [])
  const dragSplit = useCallback((x) => {
    const r = workRef.current.getBoundingClientRect()
    const v = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, (x - r.left) / r.width))
    setSplit(v); savePref('m44.split', v.toFixed(3))
  }, [])
  const dragSide = useCallback((x) => {
    const v = Math.round(Math.min(Math.min(SIDE_MAX, window.innerWidth * 0.5), Math.max(SIDE_MIN, window.innerWidth - 8 - x - 4)))
    // (x = pointer on the 8 px handle left of the panel; 8 px page padding on the right)
    setSideW(v); savePref('m44.sideW', String(v))
  }, [])

  const boxesRef = useRef(boxes)
  boxesRef.current = boxes
  const history = useRef([])
  const future = useRef([])
  const openedAt = useRef(Date.now())
  const checkSeq = useRef(0)
  const skipCheck = useRef(true) // the frame response already carries its check

  const toast = useCallback((text, kind = 'info') => {
    const id = Math.random()
    setToasts((t) => [...t.slice(-2), { id, text, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), TOAST_MS)
  }, [])
  const fail = useCallback((e) => toast(String(e), 'error'), [toast])

  const refreshFrames = useCallback(() => api.frames().then(setFrames).catch(fail), [fail])
  useEffect(() => { refreshFrames() }, [refreshFrames])
  useEffect(() => { fetchConfig().then((c) => { setLlm(c.llm); setDemo(!!c.demo) }).catch(() => {}) }, [])

  const load = useCallback((i, source = 'auto') => {
    setFrame(null); setSelected(null); setActiveFlag(null); setAddMode(false); setSavedAt(null)
    api.frame(i, init, source).then((f) => {
      skipCheck.current = true
      setFrame(f); setBoxes(f.boxes); setCheck(pickCheck(f)); setFeedback(f.feedback || {})
      setDirty(source !== 'auto')
      history.current = []; future.current = []; openedAt.current = Date.now()
    }).catch(fail)
  }, [init, fail])

  useEffect(() => {
    setPoints(null)
    load(index)
    api.points(index).then(setPoints).catch(fail)
  }, [index]) // eslint-disable-line react-hooks/exhaustive-deps

  // live check: debounced, stale answers dropped
  useEffect(() => {
    if (!frame || !ASSIST) return
    if (skipCheck.current) { skipCheck.current = false; setChecking(false); return }
    const seq = ++checkSeq.current
    setChecking(true)
    const t = setTimeout(() => {
      api.check(index, boxes).then((r) => {
        if (seq === checkSeq.current) { setCheck(pickCheck(r)); setChecking(false) }
      }).catch(fail)
    }, CHECK_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [boxes, frame, index, fail])

  useEffect(() => {
    const warn = (e) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // ---------- editing ----------
  const snapshot = useCallback(() => {
    history.current.push(boxesRef.current)
    if (history.current.length > HISTORY_MAX) history.current.shift()
    future.current = []
  }, [])

  const replaceBox = useCallback((nb) => {
    setBoxes((bs) => bs.map((b) => (b.box_id === nb.box_id ? nb : b)))
    setDirty(true)
  }, [])

  const editSelected = useCallback((fn) => {
    const b = boxesRef.current.find((x) => x.box_id === selected)
    if (!b) return
    snapshot()
    replaceBox(fn(b))
  }, [selected, snapshot, replaceBox])

  const undo = useCallback(() => {
    if (!history.current.length) return
    future.current.push(boxesRef.current)
    setBoxes(history.current.pop()); setDirty(true)
  }, [])

  const redo = useCallback(() => {
    if (!future.current.length) return
    history.current.push(boxesRef.current)
    setBoxes(future.current.pop()); setDirty(true)
  }, [])

  const addBox = useCallback((x, y) => {
    snapshot()
    const box = {
      box_id: `new_${Date.now().toString(36)}`, cls: newClass, center: [x, y, groundZ(points, x, y)],
      size: [...CLASS_SIZES[newClass]], yaw: 0, visibility: null, num_lidar_pts: null, instance: newInstance(),
    }
    setBoxes((bs) => [...bs, box]); setDirty(true); setSelected(box.box_id); setAddMode(false)
  }, [newClass, points, snapshot])

  const addProposals = useCallback((newBoxes) => {
    if (!newBoxes.length) return
    snapshot()
    setBoxes((bs) => [...bs, ...newBoxes]); setDirty(true); setSelected(newBoxes[0].box_id)
  }, [snapshot])

  const proposeOne = useCallback((cam, bbox, cls) => {
    if (!ASSIST) return
    setProposing(true)
    api.propose(index, cam, bbox, cls)
      .then((b) => {
        addProposals([b])
        const how = b.proposal.method === 'lidar_cluster' ? `${b.num_lidar_pts} điểm LiDAR` : 'ít điểm, đặt theo mặt đất'
        toast(`Gợi ý ${b.cls}: ${how}, khớp 2D ${b.proposal.fit_iou}`)
      })
      .catch(() => toast('Không gợi ý được cho box này (không có điểm LiDAR, vật quá xa)', 'error'))
      .finally(() => setProposing(false))
  }, [index, addProposals, toast])

  // copy the cuboids of the previous keyframe (ego motion + object velocity, object ids kept): labeler/propagate.py
  const [propagating, setPropagating] = useState(false)
  const propagateFrom = useCallback((direction = 'prev') => {
    if (PILOT) return
    setPropagating(true)
    api.propagate(index, boxesRef.current, direction)
      .then((r) => {
        if (r.boxes.length) { snapshot(); setBoxes((bs) => [...bs, ...r.boxes]); setDirty(true) }
        const s = r.stats
        toast(`Chép ${s.copied} cuboid từ frame ${s.from_frame}` + (s.with_motion ? ` (${s.with_motion} vật đang chạy được đẩy theo vận tốc)` : '')
          + (s.skipped_existing ? `, bỏ ${s.skipped_existing} vật đã có` : '')
          + (s.carried_verdicts ? `, mang theo ${s.carried_verdicts} cờ đã bác` : '') + '. Kiểm lại vật đã đi khỏi và thêm vật mới.')
      })
      .catch((e) => toast(String(e.message || e), 'error'))
      .finally(() => setPropagating(false))
  }, [index, snapshot, toast])

  const proposeAll = useCallback(() => {
    if (!ASSIST) return
    setProposing(true)
    api.proposeMissing(index, boxesRef.current)
      .then((r) => { addProposals(r.boxes); toast(`Gợi ý ${r.boxes.length} cuboid cho ${r.n_flags} ô thiếu (bỏ ô trùng vật / khớp kém)`) })
      .catch(fail)
      .finally(() => setProposing(false))
  }, [index, addProposals, toast, fail])

  const setVerdict = useCallback((f, kind) => {
    const key = flagKey(f)
    const next = feedback[key] === kind ? 'clear' : kind // pressing the same verdict again clears it
    setFeedback((fb) => {
      const o = { ...fb }
      if (next === 'clear') delete o[key]
      else o[key] = next
      return o
    })
    api.event(index, `flag_${next}`, { key, type: f.type, cam: f.cam, box_id: f.box_id, iou: f.iou, cls_3d: f.cls_3d, cls_2d: f.cls_2d })
  }, [feedback, index])

  const deleteBox = useCallback((id) => {
    if (!id) return
    snapshot()
    setBoxes((bs) => bs.filter((b) => b.box_id !== id)); setDirty(true)
    setSelected((s) => (s === id ? null : s))
  }, [snapshot])

  const save = useCallback(() => {
    api.save(index, boxesRef.current).then((r) => {
      setCheck(pickCheck(r)); setDirty(false); setSavedAt(new Date())
      api.event(index, 'save_time', { seconds: Math.round((Date.now() - openedAt.current) / 1000), n_boxes: boxesRef.current.length })
      refreshFrames()
    }).catch(fail)
  }, [index, refreshFrames, fail])

  const goTo = useCallback((i) => {
    if (PILOT || i === index || i < 0 || i >= frames.length) return
    if (dirty && !window.confirm('Frame này chưa lưu. Bỏ các thay đổi?')) return
    setIndex(i)
  }, [index, frames.length, dirty])

  const reset = useCallback((source) => {
    const msg = source === 'gt' ? 'Thay toàn bộ cuboid bằng GT nuScenes?' : 'Xoá hết cuboid để gán từ đầu?'
    if (window.confirm(msg)) load(index, source)
  }, [index, load])

  // ---------- derived ----------
  // verdicts: the reviewer's own on this frame, plus "false alarm" carried with a copied cuboid for the flag types
  // already dismissed on that object in the frame it was copied from (an explicit ✓ / ✗ here wins)
  const carried = useMemo(() => {
    const out = new Set()
    for (const f of check.flags) {
      const b = f.box_id && boxes.find((x) => x.box_id === f.box_id)
      if (b?.propagated?.dismissed?.includes(f.type) && !feedback[flagKey(f)]) out.add(flagKey(f))
    }
    return out
  }, [check.flags, boxes, feedback])
  const verdicts = useMemo(() => {
    const v = { ...feedback }
    for (const k of carried) v[k] = 'false_alarm'
    return v
  }, [feedback, carried])
  const visible = useCallback((f) => verdicts[flagKey(f)] !== 'false_alarm', [verdicts])
  // what the reviewer sees everywhere (summary, colours, inspector): the check minus the flags marked false alarm
  const reviewed = useMemo(() => applyVerdicts(check, (f) => !visible(f)), [check, visible])
  const status = useMemo(() => (ASSIST ? boxStatus(reviewed) : {}), [reviewed])
  const flags = useMemo(() => (!ASSIST ? [] : showDismissed ? check.flags : check.flags.filter(visible)),
    [check, visible, showDismissed])
  const proj = useMemo(() => {
    if (!frame) return {}
    const out = {}
    for (const cam of CAM_GRID) out[cam] = boxes.map((b) => projectBox(b, frame.cams[cam])).filter(Boolean)
    return out
  }, [boxes, frame])
  const colorOf = useCallback((b) => boxColor(b, status, ASSIST ? colorBy : 'class', selected), [status, colorBy, selected])
  const colors = useMemo(() => Object.fromEntries(boxes.map((b) => [b.box_id, colorOf(b)])), [boxes, colorOf])
  // the cuboid a missing-object flag predicts (TRACK_MISSING / LIDAR_UNBOXED, or a MISSING_3D on the same object)
  const missingGhost = useMemo(() => {
    const f = check.flags.find((x) => x.flag_id === activeFlag)
    return f && !f.box_id && f.detail?.box ? { ...f.detail.box, box_id: '__ghost' } : null
  }, [check.flags, activeFlag])
  const ghost = useMemo(() => {
    if (!preview) return missingGhost
    if (preview.action === 'update') {
      const b = boxes.find((x) => x.box_id === preview.box_id)
      return b ? { ...b, ...preview.box, box_id: '__ghost' } : null
    }
    return preview.action === 'create' ? { ...preview.box, box_id: '__ghost' } : null
  }, [preview, boxes, missingGhost])
  const ghostProj = useMemo(() => (ghost && frame
    ? Object.fromEntries(CAM_GRID.map((c) => [c, projectBox(ghost, frame.cams[c])])) : {}), [ghost, frame])
  useEffect(() => {  // previewing: look at it in the BEV and in its camera
    if (!ghost) return
    setFocus((f) => ({ at: ghost.center, tick: (f?.tick || 0) + 1 }))
    if (preview?.cam) setFocusCam(preview.cam)
  }, [preview]) // eslint-disable-line react-hooks/exhaustive-deps

  // the camera that shows the selected cuboid best follows the selection
  useEffect(() => {
    if (!selected) return
    const area = (cam) => { const p = proj[cam]?.find((x) => x.box_id === selected); return p ? bboxArea(p) : 0 }
    const best = CAM_GRID.reduce((a, c) => (area(c) > area(a) ? c : a), focusCam)
    if (area(best) > 0 && area(focusCam) < 0.5 * area(best)) setFocusCam(best)
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

  // live state for the 3D canvas handlers (see useBoxDrag in BevView)
  const live = useRef({})
  live.current = { addMode, addBox, selected }
  const onGroundClick = useCallback((x, y) => {
    if (live.current.addMode) live.current.addBox(x, y)
    else setSelected(null)
  }, [])
  const getSelected = useCallback(() => boxesRef.current.find((b) => b.box_id === live.current.selected), [])

  const centerOn = useCallback((id) => {
    const b = boxesRef.current.find((x) => x.box_id === id)
    if (b) setFocus((f) => ({ at: b.center, tick: (f?.tick || 0) + 1 }))
  }, [])

  // every selection made by the user glides the BEV to the cuboid (unless turned off in the viewport corner)
  const selectBox = useCallback((id) => {
    setSelected(id)
    if (id && autoCenter) centerOn(id)
  }, [autoCenter, centerOn])

  const pickFlag = useCallback((f) => {
    setActiveFlag(f.flag_id); setSelected(f.box_id); if (f.cam) setFocusCam(f.cam)
    setTab((t) => (t === 'assistant' ? t : 'issues'))
    if (f.box_id) centerOn(f.box_id)
    else if (f.detail?.box) setFocus((x) => ({ at: f.detail.box.center, tick: (x?.tick || 0) + 1 }))
  }, [centerOn])

  // ---------- assistant ----------
  const newId = () => Math.random().toString(36).slice(2)
  const activeFlagObj = check.flags.find((f) => f.flag_id === activeFlag) || null
  const updMsg = (id, fn) => setChat((c) => c.map((m) => (m.id === id ? fn(m) : m)))

  // geometric suggestion for one flag (no LLM, instant): shown as an assistant message with a card
  const askFix = useCallback((flag) => {
    if (!flag) return
    const id = newId()
    setChat((c) => [...c, { id, role: 'bot', text: '', pending: true, tools: ['suggest_fix'], suggestions: [] }])
    suggestFix(index, flag, boxesRef.current)
      .then((s) => updMsg(id, (m) => ({ ...m, pending: false, tools: [], suggestions: [s] })))
      .catch((e) => updMsg(id, (m) => ({ ...m, pending: false, error: String(e.message || e) })))
  }, [index])

  const sendChat = useCallback(async (text) => {
    const uid = newId(), bid = newId()
    setChat((c) => [...c, { id: uid, role: 'user', text }, { id: bid, role: 'bot', text: '', pending: true, tools: [], suggestions: [] }])
    setChatBusy(true)
    try {
      await chatStream({
        session_id: chatSession.current, frame_index: index, boxes: boxesRef.current, message: text,
        selected, active_flag: activeFlagObj,
      }, (ev) => {
        if (ev.type === 'text') updMsg(bid, (m) => ({ ...m, text: m.text + ev.text }))
        else if (ev.type === 'tool') updMsg(bid, (m) => ({ ...m, tools: [...m.tools, ev.name] }))
        else if (ev.type === 'suggestion') updMsg(bid, (m) => ({ ...m, suggestions: [...m.suggestions, ev.suggestion] }))
        else if (ev.type === 'error') updMsg(bid, (m) => ({ ...m, error: ev.message }))
      })
    } catch (e) {
      updMsg(bid, (m) => ({ ...m, error: String(e.message || e) }))
    }
    updMsg(bid, (m) => ({ ...m, pending: false }))
    setChatBusy(false)
  }, [index, selected, activeFlagObj])

  const onQuick = useCallback((k) => {
    if (k === 'fix') { if (llm.available) sendChat('Gợi ý cách sửa cờ đang chọn.'); else askFix(activeFlagObj) }
    else if (k === 'why') sendChat('Vì sao cuboid này bị cờ? Giải thích ngắn gọn dựa trên số liệu.')
    else if (k === 'scan') sendChat('Frame này còn những vấn đề gì? Nên xử lý cái nào trước?')
  }, [llm.available, sendChat, askFix, activeFlagObj])

  const resetAssistant = useCallback(() => {
    resetChat(chatSession.current).catch(() => {})
    chatSession.current = Math.random().toString(36).slice(2)
    setChat([]); setPreview(null); setApplied(new Set())
  }, [])

  // picking a flag while the assistant is open: show the instant geometric suggestion for it
  const lastAuto = useRef(null)
  useEffect(() => {
    if (tab !== 'assistant' || !activeFlagObj) return
    const key = flagKey(activeFlagObj) + index
    if (lastAuto.current === key) return
    lastAuto.current = key
    askFix(activeFlagObj)
  }, [tab, activeFlagObj, index, askFix])

  // new frame: a divider in the thread, no stale preview
  useEffect(() => {
    setPreview(null)
    setChat((c) => (c.length && c[c.length - 1].role !== 'divider' ? [...c, { id: newId(), role: 'divider', text: `Frame ${frames[index]?.split ?? ''} ${frames[index]?.split_index ?? index}` }] : c))
  }, [index]) // eslint-disable-line react-hooks/exhaustive-deps

  const askAbout = useCallback((f) => { setTab('assistant'); pickFlag(f) }, [pickFlag])

  const applySuggestion = useCallback((s) => {
    const b = boxesRef.current.find((x) => x.box_id === s.box_id)
    if ((s.action === 'update' || s.action === 'set_class') && !b) { toast('Cuboid này không còn trong frame', 'error'); return }
    if (s.action === 'update') { snapshot(); replaceBox({ ...b, ...s.box }) }
    else if (s.action === 'set_class') { snapshot(); replaceBox({ ...b, cls: s.cls }) }
    else if (s.action === 'delete') deleteBox(s.box_id)
    else if (s.action === 'create') {
      addProposals([{ box_id: `fix_${s.id}`, ...s.box, visibility: null, num_lidar_pts: s.after?.points ?? null, instance: s.box.instance || newInstance(),
        source: 'proposal', proposal: { method: 'fix', fit_iou: s.after?.fit_iou, cam: s.cam } }])
    } else if (s.action === 'dismiss') {
      const f = check.flags.find((g) => g.type === s.flag?.type && (g.box_id ?? null) === (s.flag?.box_id ?? null) && g.cam === s.flag?.cam)
      if (f && feedback[flagKey(f)] !== 'false_alarm') setVerdict(f, 'false_alarm')
    }
    setApplied((a) => new Set(a).add(s.id)); setPreview(null)
    api.event(index, 'suggestion_applied', { action: s.action, flag_type: s.flag_type })
    if (s.box_id && (s.action === 'update' || s.action === 'set_class')) selectBox(s.box_id)
  }, [check.flags, feedback, index, snapshot, replaceBox, deleteBox, addProposals, setVerdict, selectBox, toast])

  // ---------- keyboard ----------
  useEffect(() => {
    const onKey = (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) || lightbox) return
      const k = e.key.toLowerCase()
      const ctrl = e.ctrlKey || e.metaKey
      if (ctrl && k === 's') { e.preventDefault(); save(); return }
      if (ctrl && k === 'b') { e.preventDefault(); propagateFrom(e.shiftKey ? 'next' : 'prev'); return }
      if (ctrl && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return }
      if (ctrl && k === 'y') { e.preventDefault(); redo(); return }
      if (ctrl) return
      if (e.key === '?' || (e.shiftKey && e.code === 'Slash')) { setHelpOpen((o) => !o); return }
      if (e.key === '\\') { toggleRail(); return }
      const step = e.shiftKey ? 0.5 : 0.1
      const rot = (e.shiftKey ? 5 : 1) * DEG
      const move = { w: [step, 0, 0], s: [-step, 0, 0], a: [0, step, 0], d: [0, -step, 0], r: [0, 0, 0.05], f: [0, 0, -0.05] }[k]
      if (move && selected) {
        e.preventDefault()
        editSelected((b) => ({ ...b, center: b.center.map((v, i) => v + move[i]) }))
      } else if ((k === 'q' || k === 'e') && selected) {
        editSelected((b) => ({ ...b, yaw: b.yaw + (k === 'q' ? rot : -rot) }))
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        deleteBox(selected)
      } else if (k === 't' && selected) {
        editSelected((b) => ({ ...b, yaw: b.yaw + Math.PI }))
      } else if (k === 'c' && selected) {
        centerOn(selected)
      } else if (k === 'g' && e.shiftKey) {
        proposeAll()
      } else if (k === 'g') {
        const f = flags.find((x) => x.flag_id === activeFlag)
        if (f?.detail?.box && !f.box_id) {
          const b = f.detail.box
          addProposals([{ box_id: `miss_${Date.now().toString(36)}`, cls: b.cls, center: b.center, size: b.size, yaw: b.yaw,
            visibility: null, num_lidar_pts: f.detail.points ?? null, instance: b.instance || newInstance(),
            source: 'propagated', propagated: { from: 'interpolated', moved: 0, points: f.detail.points ?? null, motion: true } }])
          toast(`Tạo ${b.cls} ở vị trí nội suy giữa frame trước và sau`)
        } else if (f?.type === 'MISSING_3D') proposeOne(f.cam, f.det_bbox, f.cls_2d)
      } else if (k === '1' || k === '2') {
        const f = flags.find((x) => x.flag_id === activeFlag)
        if (f) setVerdict(f, k === '1' ? 'accept' : 'false_alarm')
      } else if (k === '3') {
        setMode3d((m) => !m)
      } else if (k === 'b') {
        setAddMode((m) => !m)
      } else if (k === 'v') {
        setAddMode(false)
      } else if (e.key === 'Escape') {
        if (helpOpen) setHelpOpen(false)
        else { setAddMode(false); setSelected(null) }
      } else if (k === 'n' || k === 'p') {
        if (!flags.length) return
        const j = flags.findIndex((f) => f.flag_id === activeFlag)
        pickFlag(flags[(k === 'n' ? j + 1 : j - 1 + flags.length) % flags.length])
      } else if (e.key === 'ArrowRight') {
        goTo(index + 1)
      } else if (e.key === 'ArrowLeft') {
        goTo(index - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flags, activeFlag, selected, index, helpOpen, lightbox, save, undo, redo, editSelected, deleteBox, goTo, pickFlag,
    proposeAll, proposeOne, setVerdict, centerOn, propagateFrom])

  // pilot: keep a draft on the server so a reload or a crash loses nothing
  useEffect(() => {
    if (!PILOT || !dirty) return
    const t = setTimeout(save, AUTOSAVE_MS)
    return () => clearTimeout(t)
  }, [boxes, dirty, save])

  const pilotRun = frame?.pilot?.run
  const submitPilot = useCallback(() => {
    if (!window.confirm('Nộp bài? Đồng hồ sẽ dừng và bài được chấm ngay.')) return
    api.pilotSubmit(index, boxesRef.current)
      .then((run) => { setFrame((f) => ({ ...f, pilot: { ...f.pilot, run } })); setDirty(false) })
      .catch(fail)
  }, [index, fail])

  const sel = boxes.find((b) => b.box_id === selected)
  const selFlags = flags.filter((f) => f.box_id && f.box_id === selected)
  const meta = frames[index]
  const nMissing = flags.filter((f) => f.type === 'MISSING_3D').length

  const saveState = checking ? <span className="chip"><Loader2 size={12} className="spin" /> Đang kiểm tra</span>
    : dirty ? <span className="chip warn">● Chưa lưu</span>
      : frame?.saved || savedAt ? <span className="chip ok">Đã lưu{savedAt ? ` ${savedAt.toLocaleTimeString().slice(0, 5)}` : ''}</span>
        : <span className="chip">Chưa gán</span>

  const hint = addMode ? <>Bấm lên BEV để đặt cuboid <b style={{ color: CLASS_COLORS[newClass] }}>{newClass}</b> · <kbd>Esc</kbd> huỷ</>
    : sel ? <>Kéo cuboid trên BEV, ảnh camera hoặc khung nhìn từ trên · <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> dịch · <kbd>Q</kbd><kbd>E</kbd> xoay · <kbd>R</kbd><kbd>F</kbd> nâng hạ · <kbd>C</kbd> căn giữa</>
      : <>Bấm cuboid để chọn · <kbd>B</kbd> thêm{ASSIST ? <> · <kbd>Shift</kbd><kbd>G</kbd> gợi ý · <kbd>N</kbd> cờ tiếp</> : ''} · <kbd>?</kbd> phím tắt</>

  return (
    <div className="app" style={{ gridTemplateColumns: `${railOpen ? '56px 8px' : '0px 0px'} minmax(0, 1fr) 8px ${sideW}px` }}>
      {/* ---------- top bar ---------- */}
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Boxes size={17} /></span>
          <span>M44 Labeler<small>Gán nhãn 3D · kiểm tra 2D–3D</small></span>
        </div>
        <div className="divider-v" />
        {PILOT ? (
          <>
            <span className="pilot-pill"><UserRound size={14} />{PILOT} · {ASSIST ? 'có trợ giúp' : 'không trợ giúp'}</span>
            {frame && <span className="chip">{frame.split} {frame.split_index}</span>}
            {frame?.pilot && <PilotClock started={frame.pilot.started} run={pilotRun} />}
          </>
        ) : (
          <div className="frame-nav">
            <button className="icon-btn" onClick={() => goTo(index - 1)} disabled={index <= 0} title="Frame trước (←)"><ChevronLeft size={18} /></button>
            <select className="frame-select" value={index} onChange={(e) => { goTo(Number(e.target.value)); e.target.blur() }}>
              {frames.map((f) => (
                <option key={f.index} value={f.index}>
                  {f.split} {f.split_index} · {f.sample.slice(0, 8)}{f.night ? ' · đêm' : ''}{f.labelled ? '  ✓' : ''}
                </option>
              ))}
            </select>
            <button className="icon-btn" onClick={() => goTo(index + 1)} disabled={index >= frames.length - 1} title="Frame sau (→)"><ChevronRight size={18} /></button>
          </div>
        )}
        {!PILOT && meta?.night && <span className="chip"><Moon size={12} /> đêm</span>}
        {!PILOT && meta?.labelled && <span className="chip ok">đã gán</span>}
        <span className="grow" />
        {saveState}
        {ASSIST && (
          <button className="btn" onClick={proposeAll} disabled={proposing || !frame} title="Shift+G">
            {proposing ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Gợi ý từ ảnh
            {nMissing > 0 && <span className="count">{nMissing}</span>}
          </button>
        )}
        <button className="icon-btn" onClick={undo} title="Hoàn tác (Ctrl+Z)"><Undo2 size={17} /></button>
        <button className="icon-btn" onClick={redo} title="Làm lại (Ctrl+Y)"><Redo2 size={17} /></button>
        {PILOT ? (
          frame && !pilotRun && <button className="btn primary" onClick={submitPilot}><Send size={15} /> Nộp bài</button>
        ) : (
          <button className="btn primary" onClick={save} disabled={!dirty} title="Ctrl+S"><Save size={15} /> Lưu</button>
        )}
        {!PILOT && (
          <Menu trigger={(toggle, open) => (
            <button className={`icon-btn ${open ? 'on' : ''}`} onClick={toggle} title="Thêm"><MoreHorizontal size={18} /></button>
          )}>
            <div className="menu-label">Frame chưa gán mở với</div>
            <div style={{ padding: '2px 10px 8px' }} onClick={(e) => e.stopPropagation()}>
              <div className="seg">
                {[['gt', 'GT nuScenes'], ['empty', 'Rỗng']].map(([v, l]) => (
                  <button key={v} className={init === v ? 'on' : ''} onClick={() => { setInit(v); savePref('m44.init', v) }}>{l}</button>
                ))}
              </div>
            </div>
            <div className="menu-sep" />
            <button className="menu-item" onClick={() => reset('gt')}><RotateCcw size={15} /> Đặt lại về GT</button>
            <button className="menu-item" onClick={() => reset('empty')}><Trash2 size={15} /> Xoá hết cuboid</button>
            <div className="menu-sep" />
            <a className="menu-item" href={api.exportUrl('nuscenes')}><Download size={15} /> Xuất nuScenes<span className="hint">mọi frame đã lưu</span></a>
            <a className="menu-item" href={api.exportUrl('raw')}><FileJson size={15} /> Xuất JSON<span className="hint">hệ LiDAR</span></a>
          </Menu>
        )}
        <button className="icon-btn" onClick={() => setHelpOpen(true)} title="Phím tắt (?)"><CircleHelp size={18} /></button>
      </header>

      {/* ---------- tool rail ---------- */}
      <nav className="rail" style={railOpen ? undefined : { display: 'none' }}>
        <Tool icon={MousePointer2} label="Chọn / chỉnh" keys="V" on={!addMode} onClick={() => setAddMode(false)} />
        <Tool icon={BoxSelect} label="Thêm cuboid" keys="B" on={addMode} onClick={() => setAddMode((m) => !m)} />
        {!PILOT && <Tool icon={CopyPlus} label="Chép cuboid từ frame trước" keys="Ctrl B" disabled={propagating || !frame}
          onClick={() => propagateFrom('prev')} />}
        {ASSIST && <Tool icon={Sparkles} label="Gợi ý mọi ô thiếu" keys="Shift G" disabled={proposing} onClick={proposeAll} />}
        <div className="rail-sep" />
        <Tool icon={Crosshair} label="Căn giữa cuboid đang chọn" keys="C" disabled={!selected} onClick={() => centerOn(selected)} />
        <Tool icon={Rotate3d} label="Xoay 3D" keys="3" on={mode3d} onClick={() => setMode3d((m) => !m)} />
        <span className="grow" />
        <Tool icon={CircleHelp} label="Phím tắt" keys="?" onClick={() => setHelpOpen(true)} />
        <Tool icon={PanelLeftClose} label="Thu gọn thanh công cụ" keys="\" onClick={toggleRail} />
      </nav>

      {/* ---------- workspace ---------- */}
      <main className="work" ref={workRef} style={{ gridTemplateColumns: `minmax(0, ${split}fr) 8px minmax(0, ${1 - split}fr)` }}>
        <section className="viewport" style={{ cursor: addMode ? 'crosshair' : undefined }}>
          {!railOpen && (
            <button className="glass icon-btn rail-open" onClick={toggleRail} title="Mở thanh công cụ (\)"><PanelLeftOpen size={16} /></button>
          )}
          {frame && <BevView points={points} boxes={boxes} colorOf={colorOf} selected={selected} onSelect={selectBox}
            mode3d={mode3d} addMode={addMode} onGroundClick={onGroundClick} getSelected={getSelected}
            onDragStart={snapshot} onBoxChange={replaceBox} focus={focus} ghost={ghost}
            passXY={ASSIST && selected ? check.qc?.[selected]?.pass_xy : null} />}
          {!frame && <div className="empty" style={{ paddingTop: 120 }}><Loader2 size={26} className="spin" /><div>Đang tải frame…</div></div>}

          <div className="overlay tl">
            {addMode && (
              <div className="glass class-picker">
                {CLASSES.map((c) => (
                  <button key={c} className={`class-chip ${newClass === c ? 'on' : ''}`}
                    onClick={() => { setNewClass(c); savePref('m44.newClass', c) }}>
                    <span className="dot" style={{ background: CLASS_COLORS[c] }} />{c}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="overlay tr">
            <button className={`glass icon-btn ${autoCenter ? 'on' : ''}`} style={{ width: 34, height: 34, padding: 0 }}
              title={autoCenter ? 'Tự căn giữa khi chọn cuboid: bật' : 'Tự căn giữa khi chọn cuboid: tắt'}
              onClick={() => setAutoCenter((a) => { savePref('m44.autoCenter', a ? '0' : '1'); return !a })}>
              <Crosshair size={16} />
            </button>
            {ASSIST && !addMode && (
              <div className="glass" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <Layers size={14} style={{ color: 'var(--text-3)' }} />
                <div className="seg">
                  {[['class', 'Class'], ['status', 'Kiểm tra']].map(([v, l]) => (
                    <button key={v} className={colorBy === v ? 'on' : ''} onClick={() => { setColorBy(v); savePref('m44.colorBy', v) }}>{l}</button>
                  ))}
                </div>
                <div className="legend">
                  {colorBy === 'status' ? (
                    <><span><i className="swatch" style={{ background: COLORS.ok }} />đã kiểm</span>
                      <span><i className="swatch" style={{ background: COLORS.flagged }} />cờ</span>
                      <span><i className="swatch" style={{ background: COLORS.unchecked }} />không kiểm</span></>
                  ) : <span><i className="swatch" style={{ background: COLORS.flagged }} />có cờ</span>}
                </div>
              </div>
            )}
          </div>
          {sel && (
            <div className="overlay bl">
              <div className="sideviews">
                <div className="glass sidecard">
                  <div className="side-head"><span>Nhìn từ trên</span><span>đầu xe → · ● kéo để xoay</span></div>
                  <TopView box={sel} points={points} onDragStart={snapshot} onChange={replaceBox} />
                </div>
                {[['side', 'Nhìn ngang', 'đầu xe →'], ['back', 'Nhìn từ sau', '']].map(([v, title, note]) => (
                  <div key={v} className="glass sidecard">
                    <div className="side-head"><span>{title}</span><span>{note}</span></div>
                    <SideView box={sel} points={points} view={v} onDragStart={snapshot} onChange={replaceBox} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        <Splitter title="Kéo để đổi kích thước BEV / camera · bấm đúp: mặc định" onDrag={dragSplit}
          onReset={() => { setSplit(SPLIT_DEFAULT); savePref('m44.split', String(SPLIT_DEFAULT)) }} />

        <section className="cameras">
          {frame && (
            <>
              <div className="cam-focus">
                <div className="cam-focus-head">
                  <b>{focusCam.replace('CAM_', '').replace('_', ' ')}</b>
                  <span className="chip plain" style={{ background: 'rgba(0,0,0,0.4)' }}>{proj[focusCam]?.length || 0} cuboid</span>
                  {ASSIST && flags.some((f) => f.cam === focusCam) && (
                    <span className="chip danger"><TriangleAlert size={12} /> {flags.filter((f) => f.cam === focusCam).length} cờ</span>
                  )}
                  <span className="grow" />
                  {ASSIST && <span style={{ color: 'rgba(230,234,242,0.6)' }}>bấm ô vàng để gợi ý</span>}
                  <button className="icon-btn sm" onClick={() => setLightbox(focusCam)} title="Phóng to toàn màn hình (bấm vào ảnh)">
                    <Maximize2 size={14} />
                  </button>
                </div>
                <CameraView frameIndex={index} cam={focusCam} proj={proj[focusCam]} flags={flags}
                  dets={ASSIST ? frame.dets : []} colors={colors} selected={selected} onSelect={selectBox}
                  onPropose={proposeOne} label={sel ? sel.cls : null} onBackground={() => setLightbox(focusCam)}
                  ghost={ghostProj[focusCam]} box={sel} cal={frame.cams[focusCam]} onDragStart={snapshot}
                  onBoxChange={replaceBox} />
              </div>
              <div className="cam-thumbs">
                {CAM_GRID.map((cam) => (
                  <div key={cam} className={`cam-thumb ${cam === focusCam ? 'on' : ''}`} onClick={() => setFocusCam(cam)}
                    onDoubleClick={() => setLightbox(cam)} title="Bấm: xem lớn bên trên · bấm đúp: toàn màn hình">
                    <CameraView thumb frameIndex={index} cam={cam} proj={proj[cam]} flags={flags} dets={[]}
                      colors={colors} selected={selected} onSelect={() => {}} onPropose={() => {}} ghost={ghostProj[cam]} />
                  </div>
                ))}
              </div>
              <FrameSummary boxes={boxes} qc={reviewed.qc} coverage={check.coverage} assist={ASSIST} nDets={frame.dets.length} />
            </>
          )}
        </section>
      </main>

      {/* ---------- side panel ---------- */}
      <div className="side-split">
        <Splitter title="Kéo để đổi độ rộng panel · bấm đúp: mặc định" onDrag={dragSide}
          onReset={() => { setSideW(SIDE_DEFAULT); savePref('m44.sideW', String(SIDE_DEFAULT)) }} />
      </div>
      <aside className="side">
        {pilotRun && <PilotResult run={pilotRun} />}
        <div className="tabs">
          <button className={`tab ${tab === 'objects' ? 'on' : ''}`} onClick={() => setTab('objects')}>
            Đối tượng <span className="count">{boxes.length}</span>
          </button>
          {ASSIST && (
            <button className={`tab ${tab === 'issues' ? 'on' : ''}`} onClick={() => setTab('issues')}>
              Kiểm tra <span className={`count ${flags.length ? 'danger' : ''}`}>{flags.length}</span>
            </button>
          )}
          {ASSIST && (
            <button className={`tab ${tab === 'assistant' ? 'on' : ''}`} onClick={() => setTab('assistant')}>
              <Bot size={14} /> Trợ lý
            </button>
          )}
        </div>
        {tab === 'assistant' && ASSIST ? (
          <AssistantPanel llm={llm} messages={chat} busy={chatBusy} onSend={sendChat} onQuick={onQuick} onReset={resetAssistant}
            preview={preview} applied={applied} onPreview={setPreview} onApply={applySuggestion} hasFlag={!!activeFlagObj} />
        ) : tab === 'issues' && ASSIST ? (
          <IssuesPanel flags={flags} allFlags={check.flags} feedback={verdicts} carried={carried} activeFlag={activeFlag} onPick={pickFlag}
            onVerdict={setVerdict} showDismissed={showDismissed} setShowDismissed={setShowDismissed} onAsk={askAbout} />
        ) : (
          <ObjectsPanel boxes={boxes} status={status} selected={selected} onSelect={selectBox} onDelete={deleteBox} assist={ASSIST} />
        )}
        {sel && tab !== 'assistant' && <Inspector box={sel} status={status} qc={reviewed.qc?.[sel.box_id]} flags={selFlags} assist={ASSIST} onEdit={editSelected}
          onDelete={() => deleteBox(sel.box_id)} onClose={() => { setSelected(null); setActiveFlag(null) }} />}
      </aside>

      {/* ---------- status bar ---------- */}
      <footer className="statusbar">
        <span className="hint">{hint}</span>
        <span className="grow" />
        {demo && <><span className="stat-item" title="Nhãn bạn lưu chỉ trình duyệt này thấy. Dữ liệu: nuScenes-mini (Motional), CC BY-NC-SA 4.0 – không phải sản phẩm của Motional.">
          Bản demo · 2 scene nuScenes-mini · nuScenes © Motional, CC BY-NC-SA 4.0</span><span className="sep" /></>}
        <span className="stat-item"><b>{boxes.length}</b> cuboid</span>
        {ASSIST && <><span className="sep" /><span className="stat-item"><b>{flags.length}</b> cờ</span>
          <span className="sep" /><span className="stat-item"><b>{frame?.dets.length ?? 0}</b> vật YOLO</span></>}
        {frame && <><span className="sep" /><span className="stat-item">{frame.split} {frame.split_index} · {frame.sample.slice(0, 8)}</span></>}
      </footer>

      <Toasts items={toasts} onClose={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
      {lightbox && frame && (
        <Lightbox cams={CAM_GRID} cam={lightbox} setCam={(c) => { setLightbox(c); setFocusCam(c) }} onClose={() => setLightbox(null)}
          cameraProps={{
            frameIndex: index, proj: proj[lightbox], flags, dets: ASSIST ? frame.dets : [], colors, selected,
            onSelect: selectBox, onPropose: proposeOne, label: sel ? sel.cls : null, ghost: ghostProj[lightbox],
            box: sel, cal: frame.cams[lightbox], onDragStart: snapshot, onBoxChange: replaceBox,
          }} />
      )}
      {helpOpen && <ShortcutsDialog assist={ASSIST} pilot={!!PILOT} onClose={() => setHelpOpen(false)} />}
    </div>
  )
}
