import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Camera, Check, CheckCircle2, ChevronDown, ChevronUp, CircleDashed, CopyPlus, Eye, EyeOff, Fingerprint, FlipHorizontal2, History, Inbox, Info, Radar,
  ShieldAlert, ShieldCheck, Sparkles, Trash2, Wand2, X,
} from 'lucide-react'
import { CLASSES, CLASS_COLORS } from './geometry.js'

export const FLAG_LABEL = {
  LOW_IOU: 'Lệch vị trí', SIZE_MISMATCH: 'Sai kích thước', CLASS_MISMATCH: 'Sai class',
  NO_2D_MATCH: 'Không khớp ảnh', MISSING_3D: 'Thiếu cuboid',
  // LiDAR (labeler/lidar_qc.py)
  LIDAR_EMPTY: 'Cuboid rỗng', LIDAR_FREE: 'Lấn khoảng trống', LIDAR_SPILL: 'Điểm tràn ra ngoài',
  LIDAR_HEADING: 'Lệch hướng điểm', SIZE_IMPLAUSIBLE: 'Kích thước phi lý', FLOATING: 'Lơ lửng', SUNKEN: 'Chìm',
  BEV_OVERLAP: 'Chồng nhau',
  // temporal (labeler/track.py)
  TRACK_SIZE: 'Nhảy kích thước', TRACK_JUMP: 'Nhảy vị trí', TRACK_YAW: 'Nhảy hướng', TRACK_CLASS: 'Đổi class',
}

export const SOURCE = {
  camera: { label: 'Camera', icon: Camera },
  lidar: { label: 'LiDAR', icon: Radar },
  track: { label: 'Thời gian', icon: History },
}

// stable across checks (flag_id is renumbered every time): type + cuboid or detection + camera; LiDAR / temporal
// flags are about the cuboid itself (their camera is only where to look, and follows the edits)
export const flagKey = (f) => (f.source && f.source !== 'camera' ? `${f.type}|${f.box_id ?? ''}|${f.source}`
  : `${f.type}|${f.box_id ?? ''}|${f.cam}|${f.det_bbox && !f.box_id ? f.det_bbox.map(Math.round).join(',') : ''}`)

const camName = (cam) => (cam ? cam.replace('CAM_', '').replace('_', ' ') : 'BEV')

// tag on LiDAR / temporal flags (camera flags are the default and stay untagged)
export function SourceTag({ source }) {
  if (!source || source === 'camera') return null
  const s = SOURCE[source]
  const Icon = s.icon
  return <span className={`src-tag ${source}`} title={`Cờ từ ${s.label}`}><Icon size={11} />{s.label}</span>
}

export function StatusIcon({ st, size = 15 }) {
  if (st === 'flagged') return <AlertTriangle size={size} className="st-flag" />
  if (st === 'ok') return <CheckCircle2 size={size} className="st-ok" />
  return <CircleDashed size={size} className="st-none" />
}

// ---------- objects ----------

export function ObjectsPanel({ boxes, status, selected, onSelect, onDelete, assist }) {
  const [q, setQ] = useState('')
  const selRef = useRef(null)
  useEffect(() => { selRef.current?.scrollIntoView({ block: 'nearest' }) }, [selected])

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const g = {}
    for (const b of boxes) {
      if (needle && !b.cls.includes(needle) && !b.box_id.toLowerCase().includes(needle)) continue
      ;(g[b.cls] ||= []).push(b)
    }
    for (const list of Object.values(g)) list.sort((a, b) => Math.hypot(...a.center.slice(0, 2)) - Math.hypot(...b.center.slice(0, 2)))
    return CLASSES.filter((c) => g[c]).map((c) => [c, g[c]]).concat(Object.entries(g).filter(([c]) => !CLASSES.includes(c)))
  }, [boxes, q])

  return (
    <>
      <div className="panel-tools">
        <input className="search" placeholder="Tìm class hoặc id…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="panel-body">
        {!boxes.length && (
          <div className="empty"><span className="empty-icon"><Inbox size={24} /></span><div>Chưa có cuboid nào.</div>
            <div>Bấm <kbd>B</kbd> rồi bấm lên BEV{assist ? <>, hoặc <kbd>Shift</kbd>+<kbd>G</kbd> để gợi ý từ ảnh</> : ''}.</div></div>
        )}
        {groups.map(([cls, list]) => (
          <div key={cls}>
            <div className="group-head">
              <span className="dot" style={{ background: CLASS_COLORS[cls] }} />{cls}<span className="count">{list.length}</span>
            </div>
            {list.map((b) => {
              const on = b.box_id === selected
              return (
                <div key={b.box_id} ref={on ? selRef : null} className={`row ${on ? 'on' : ''}`} onClick={() => onSelect(b.box_id)}
                  style={{ '--bar': CLASS_COLORS[b.cls] }}>
                  {assist && <StatusIcon st={status[b.box_id]} />}
                  <span className="id">{b.box_id.length > 14 ? `…${b.box_id.slice(-10)}` : b.box_id}</span>
                  {b.source === 'proposal' && <Sparkles size={13} style={{ color: '#9ec0ff' }} title="gợi ý từ ảnh" />}
                  {b.source === 'propagated' && <CopyPlus size={13} style={{ color: 'var(--track)' }} title="chép từ frame trước" />}
                  <span className="meta">{Math.hypot(b.center[0], b.center[1]).toFixed(1)} m</span>
                  <button className="icon-btn sm trash" title="Xoá (Del)" onClick={(e) => { e.stopPropagation(); onDelete(b.box_id) }}>
                    <Trash2 size={13} />
                  </button>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </>
  )
}

// ---------- issues ----------

export function IssuesPanel({ flags: allShown, allFlags, feedback, carried, activeFlag, onPick, onVerdict, showDismissed, setShowDismissed, onAsk }) {
  const [src, setSrc] = useState('all')
  const flags = useMemo(() => (src === 'all' ? allShown : allShown.filter((f) => (f.source || 'camera') === src)), [allShown, src])
  const nBySource = useMemo(() => {
    const c = { all: allShown.length }
    for (const f of allShown) c[f.source || 'camera'] = (c[f.source || 'camera'] || 0) + 1
    return c
  }, [allShown])
  const nDismissed = allFlags.filter((f) => feedback[flagKey(f)] === 'false_alarm').length
  const byType = useMemo(() => {
    const c = {}
    for (const f of flags) c[f.type] = (c[f.type] || 0) + 1
    return Object.entries(c)
  }, [flags])
  const activeRef = useRef(null)
  useEffect(() => { activeRef.current?.scrollIntoView({ block: 'nearest' }) }, [activeFlag])

  return (
    <>
      <div className="panel-tools" style={{ flexWrap: 'wrap' }}>
        <div className="seg src-seg">
          {[['all', 'Tất cả'], ['camera', 'Camera'], ['lidar', 'LiDAR'], ['track', 'Thời gian']].map(([v, l]) => (
            <button key={v} className={src === v ? 'on' : ''} onClick={() => setSrc(v)}>{l}<span className="n">{nBySource[v] || 0}</span></button>
          ))}
        </div>
        {byType.length ? byType.map(([t, n]) => <span key={t} className={`badge ${t}`}>{FLAG_LABEL[t] || t} · {n}</span>)
          : <span className="chip ok"><ShieldCheck size={13} /> Không còn cờ</span>}
      </div>
      <div className="panel-body">
        {nDismissed > 0 && (
          <div className="toggle-line" onClick={() => setShowDismissed(!showDismissed)}>
            {showDismissed ? <EyeOff size={14} /> : <Eye size={14} />}
            {showDismissed ? 'Ẩn' : 'Hiện'} {nDismissed} cờ đã đánh dấu báo động giả
          </div>
        )}
        {!flags.length && (
          <div className="empty"><span className="empty-icon"><ShieldCheck size={24} className="st-ok" /></span>
            <div>{src === 'all' ? 'Không còn cờ: mọi cuboid kiểm được đều ổn.' : `Không có cờ ${SOURCE[src].label}.`}</div></div>
        )}
        {flags.map((f, i) => {
          const verdict = feedback[flagKey(f)]
          const on = f.flag_id === activeFlag
          const sure = f.certainty === 'high'
          const head = (i === 0 || flags[i - 1].certainty !== f.certainty) && f.certainty && (
            <div key={`h-${f.certainty}`} className={`flag-group ${sure ? 'sure' : ''}`}>
              {sure ? <ShieldAlert size={14} /> : <Eye size={14} />}
              <b>{sure ? 'Chắc chắn' : 'Cần xem'}</b>
              <span className="count">{flags.filter((g) => g.certainty === f.certainty).length}</span>
              <span className="hint">{sure ? '≥ 2 nguồn cùng báo – gần như chắc chắn sai, sửa trước'
                : '1 nguồn – xem bằng chứng trước khi sửa, có thể là báo động giả'}</span>
            </div>
          )
          return [head,
            <div key={f.flag_id} ref={on ? activeRef : null} className={`row flag-row ${sure ? 'sure' : ''} ${on ? 'on' : ''} ${verdict === 'false_alarm' ? 'dim' : ''}`}
              onClick={() => onPick(f)} style={{ '--bar': f.type === 'MISSING_3D' ? 'var(--missing)' : 'var(--danger)' }}>
              <div className="flag-line">
              <span className={`badge ${f.type}`}>{FLAG_LABEL[f.type] || f.type}</span>
              <span>{f.cls_3d || f.cls_2d}</span>
              <SourceTag source={f.source} />
              {carried?.has(flagKey(f)) && <span className="carried" title="Loại cờ này đã được bác trên chính vật này ở frame được chép sang">bác ở frame trước</span>}
              <span className="meta">{(f.source || 'camera') === 'camera' ? camName(f.cam) : ''}{f.iou != null ? ` · ${f.iou.toFixed(2)}` : ''}</span>
              <span className="actions">
                {onAsk && (
                  <button className="icon-btn sm" title="Hỏi trợ lý cách sửa" onClick={(e) => { e.stopPropagation(); onAsk(f) }}>
                    <Wand2 size={14} />
                  </button>
                )}
                <button className={`icon-btn sm verdict ${verdict === 'accept' ? 'on-accept' : ''}`} title="Đúng là lỗi (1)"
                  onClick={(e) => { e.stopPropagation(); onVerdict(f, 'accept') }}><Check size={14} /></button>
                <button className={`icon-btn sm verdict ${verdict === 'false_alarm' ? 'on-false' : ''}`} title="Báo động giả (2)"
                  onClick={(e) => { e.stopPropagation(); onVerdict(f, 'false_alarm') }}><X size={14} /></button>
              </span>
              </div>
              {on && f.msg && <div className="flag-msg">{f.msg}</div>}
              {on && sure && f.sources?.length > 1 && (
                <div className="flag-msg">Cuboid này bị {f.sources.map((s) => SOURCE[s].label).join(' + ')} cùng gắn cờ.</div>
              )}
            </div>]
        })}
      </div>
    </>
  )
}

// ---------- inspector ----------

// Number box: every valid value applies at once (typing or spinner arrows), so the cuboid moves while you type;
// the text is only re-formatted from the box when the field is not being edited.
function NumField({ label, value, step, onCommit, digits = 2, unit = 'm' }) {
  const [text, setText] = useState(value.toFixed(digits))
  const editing = useRef(false)
  useEffect(() => { if (!editing.current) setText(value.toFixed(digits)) }, [value, digits])
  return (
    <div className="field">
      <label>{label}</label>
      <input type="number" step={step} value={text}
        onFocus={() => { editing.current = true }}
        onChange={(e) => {
          setText(e.target.value)
          const v = parseFloat(e.target.value)
          if (Number.isFinite(v) && Math.abs(v - value) > 1e-9) onCommit(v)
        }}
        onBlur={() => { editing.current = false; setText(value.toFixed(digits)) }}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur() }} />
      <span className="unit">{unit}</span>
    </div>
  )
}

const LEVEL = {
  high: ['ok', 'Tin cậy QC cao'], medium: ['accent', 'Tin cậy QC vừa'], flagged: ['danger', 'Có cờ'], none: ['', 'Chưa kiểm được'],
}

function QcRows({ qc }) {
  const r = qc.rays || {}
  const rows = [
    ['camera', qc.camera, qc.camera === 'none' ? 'xa, bị che hoặc class YOLO không nhận' : qc.camera === 'ok' ? 'khớp vật YOLO' : 'lệch ảnh'],
    ['lidar', qc.lidar, r.rays != null
      ? `${r.hit ?? 0} tia chạm · ${r.pass ?? 0} xuyên qua · ${r.occ ?? 0} bị che · ${qc.n_inside} điểm`
      : `${qc.n_inside} điểm trong cuboid`],
    ['track', qc.track, qc.n_obs ? `vật này có ở ${qc.n_obs} frame khác` : 'chưa thấy vật này ở frame khác'],
  ]
  return (
    <div className="qc-rows">
      {rows.map(([src, st, text]) => {
        const S = SOURCE[src]
        return (
          <div key={src} className={`qc-row ${st}`}>
            <StatusIcon st={st === 'none' ? 'unchecked' : st} size={14} />
            <b><S.icon size={12} />{S.label}</b>
            <span>{st === 'none' ? `không kiểm được – ${text}` : text}</span>
          </div>
        )
      })}
    </div>
  )
}

const loadFlag = (k) => { try { return localStorage.getItem(k) === '1' } catch { return false } }
const saveFlag = (k, v) => { try { localStorage.setItem(k, v ? '1' : '0') } catch { /* private mode */ } }

// object id: edit to merge two ids that are the same object (e.g. drawn twice in different frames)
function InstanceField({ value, onCommit }) {
  const [text, setText] = useState(value)
  useEffect(() => { setText(value) }, [value])
  const commit = () => { const v = text.trim(); if (v && v !== value) onCommit(v); else setText(value) }
  return (
    <div className="field inst-field" title="Cùng một vật ở các frame phải cùng mã để kiểm tra theo thời gian nối được">
      <label><Fingerprint size={13} /></label>
      <input value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} spellCheck={false}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { setText(value); e.currentTarget.blur() } }} />
    </div>
  )
}

export function Inspector({ box, status, qc, flags, assist, onEdit, onDelete, onClose }) {
  const deg = (box.yaw * 180) / Math.PI
  const set = (fn) => onEdit(fn)
  const st = status[box.box_id]
  // collapsed: only the header stays, so the list above (flags, objects) gets the room back; remembered
  const [collapsed, setCollapsed] = useState(() => loadFlag('m44.inspCollapsed'))
  const toggle = () => setCollapsed((c) => { saveFlag('m44.inspCollapsed', !c); return !c })
  return (
    <div className={`inspector ${collapsed ? 'collapsed' : ''}`}>
      <div className="insp-head">
        <span className="dot" style={{ background: CLASS_COLORS[box.cls], width: 12, height: 12 }} />
        <select value={box.cls} onChange={(e) => { const c = e.target.value; set((b) => ({ ...b, cls: c })); e.target.blur() }}>
          {CLASSES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <span className="grow" />
        {assist && <StatusIcon st={st} />}
        <span className="idtag">{box.box_id.slice(-10)}</span>
        <span className="insp-btns">
          <button className="icon-btn sm" onClick={toggle} title={collapsed ? 'Mở rộng bảng thuộc tính' : 'Thu gọn bảng thuộc tính'}>
            {collapsed ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
          {onClose && (
            <button className="icon-btn sm" onClick={onClose} title="Đóng – bỏ chọn cuboid (Esc)"><X size={15} /></button>
          )}
        </span>
      </div>
      {!collapsed && <>
      <div className="insp-sec">Vị trí đáy</div>
      <div className="fields">
        {['X', 'Y', 'Z'].map((l, i) => (
          <NumField key={l} label={l} value={box.center[i]} step={0.05}
            onCommit={(v) => set((b) => ({ ...b, center: b.center.map((c, j) => (j === i ? v : c)) }))} />
        ))}
      </div>
      <div className="insp-sec">Kích thước · hướng</div>
      <div className="fields">
        {['L', 'W', 'H'].map((l, i) => (
          <NumField key={l} label={l} value={box.size[i]} step={0.05}
            onCommit={(v) => set((b) => ({ ...b, size: b.size.map((c, j) => (j === i ? Math.max(0.1, v) : c)) }))} />
        ))}
        <NumField label="θ" unit="°" value={deg} step={1} digits={1} onCommit={(v) => set((b) => ({ ...b, yaw: (v * Math.PI) / 180 }))} />
      </div>
      {assist && (
        <div className="insp-note">
          {flags.length ? <><AlertTriangle size={14} className="st-flag" />{flags.map((f) => `${FLAG_LABEL[f.type] || f.type} (${(f.source || 'camera') === 'camera' ? camName(f.cam) : SOURCE[f.source].label})`).join(' · ')}</>
            : st === 'ok' ? <><CheckCircle2 size={14} className="st-ok" />Đã kiểm, không có cờ</>
              : <><Info size={14} />Chưa nguồn nào kiểm được: xa, bị che, ít điểm LiDAR và chưa có ở frame khác</>}
        </div>
      )}
      {assist && qc && (
        <>
          <div className="insp-sec qc-head">Kiểm tra QC<span className={`chip ${LEVEL[qc.level][0]}`}>{LEVEL[qc.level][1]}</span></div>
          <QcRows qc={qc} />
        </>
      )}
      <div className="insp-sec">Mã vật (nối giữa các frame)</div>
      <InstanceField value={box.instance || ''} onCommit={(v) => set((b) => ({ ...b, instance: v }))} />
      {box.source === 'propagated' && box.propagated && (
        <div className="insp-note">
          <CopyPlus size={14} style={{ color: 'var(--track)' }} />
          Chép từ frame trước{box.propagated.motion ? ', đẩy theo vận tốc của vật' : ''} – kiểm lại vị trí rồi chỉnh nếu cần
        </div>
      )}
      {box.source === 'proposal' && box.proposal && (
        <div className="insp-note">
          <Sparkles size={14} style={{ color: '#9ec0ff' }} />
          Gợi ý từ {camName(box.proposal.cam || '')}: {box.proposal.method === 'lidar_cluster' ? `${box.num_lidar_pts} điểm LiDAR` : 'đặt theo mặt đất'}, khớp 2D {box.proposal.fit_iou}
        </div>
      )}
      <div className="insp-actions">
        <button className="btn sm" onClick={() => set((b) => ({ ...b, yaw: b.yaw + Math.PI }))} title="T">
          <FlipHorizontal2 size={14} /> Quay đầu 180°
        </button>
        <span className="grow" />
        <button className="btn sm danger" onClick={onDelete} title="Del"><Trash2 size={14} /> Xoá</button>
      </div>
      </>}
    </div>
  )
}

// ---------- pilot result ----------

export function PilotResult({ run }) {
  const pct = run.targets ? Math.round((100 * run.target_correct) / run.targets) : 0
  return (
    <div className="result">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className="big">{run.target_correct} / {run.targets}</span>
        <span className="chip accent">{run.minutes} phút</span>
      </div>
      <div className="sub">vật gán đúng ({pct} %)</div>
      <div className="stats">
        <div className="stat"><b>{run.target_rough}</b><span>gán lệch</span></div>
        <div className="stat"><b>{run.target_missed}</b><span>bỏ sót</span></div>
        <div className="stat"><b>{run.wrong}</b><span>sai / thừa</span></div>
      </div>
      <div className="sub">Đúng = tâm ≤ 0,7 m, cạnh ±25 %, hướng ≤ 20°. Mục tiêu = car, người thấy ≥ 60 %, trong 30 m.</div>
    </div>
  )
}

// ---------- frame summary (under the cameras) ----------

export function FrameSummary({ boxes, qc = {}, coverage = {}, assist, nDets }) {
  const byClass = CLASSES.map((c) => [c, boxes.filter((b) => b.cls === c).length]).filter(([, n]) => n)
  const n = boxes.length || 1
  const lv = (l) => boxes.filter((b) => qc[b.box_id]?.level === l).length
  const high = lv('high'), mid = lv('medium'), bad = lv('flagged')
  const none = boxes.length - high - mid - bad
  const pc = (v) => `${Math.round(100 * (v || 0))}%`
  return (
    <div className="summary">
      <div className="summary-head">Tổng quan frame<span className="grow" /><span>{boxes.length} cuboid</span></div>
      {assist && boxes.length > 0 && (
        <>
          <div className="meter">
            <i style={{ width: `${(100 * high) / n}%`, background: 'var(--ok)' }} />
            <i style={{ width: `${(100 * mid) / n}%`, background: 'var(--ok-mid)' }} />
            <i style={{ width: `${(100 * bad) / n}%`, background: 'var(--danger)' }} />
            <i style={{ width: `${(100 * none) / n}%`, background: 'var(--raise-2)' }} />
          </div>
          <div className="meter-legend">
            <span title="Ít nhất 2 nguồn (camera, LiDAR, thời gian) xác nhận"><i style={{ background: 'var(--ok)' }} />{high} tin cậy cao</span>
            <span title="1 nguồn xác nhận"><i style={{ background: 'var(--ok-mid)' }} />{mid} vừa</span>
            <span><i style={{ background: 'var(--danger)' }} />{bad} có cờ</span>
            <span><i style={{ background: 'var(--raise-2)' }} />{none} chưa kiểm</span>
            <span className="grow" /><span>{nDets} vật YOLO</span>
          </div>
          <div className="coverage" title="Tỉ lệ cuboid mỗi nguồn kiểm được (có thể đánh giá đúng / sai)">
            {['camera', 'lidar', 'track'].map((s) => {
              const S = SOURCE[s]
              return <span key={s} className={`cov ${s}`}><S.icon size={12} />{S.label}<b>{pc(coverage[s])}</b></span>
            })}
            <span className="cov total">kiểm được<b>{pc(coverage.any)}</b></span>
          </div>
        </>
      )}
      <div className="class-counts">
        {byClass.length ? byClass.map(([c, k]) => (
          <span key={c} className="class-count"><span className="dot" style={{ background: CLASS_COLORS[c] }} />{c}<b>{k}</b></span>
        )) : <span style={{ color: 'var(--text-3)' }}>Chưa có cuboid</span>}
      </div>
    </div>
  )
}
