import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Keyboard, Timer, X } from 'lucide-react'

export function Tool({ icon: Icon, label, keys, on, disabled, onClick }) {
  return (
    <button className={`tool ${on ? 'on' : ''}`} disabled={disabled} onClick={onClick} aria-label={label}>
      <Icon size={19} strokeWidth={1.8} />
      <span className="tip">{label}{keys && <> <kbd>{keys}</kbd></>}</span>
    </button>
  )
}

// dropdown that closes on an outside click or Escape
export function Menu({ trigger, children }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="menu-wrap" ref={ref}>
      {trigger(() => setOpen((o) => !o), open)}
      {open && <div className="menu" onClick={() => setOpen(false)}>{children}</div>}
    </div>
  )
}

export function PilotClock({ started, run }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (run) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [run])
  const sec = Math.max(0, Math.round((run ? run.submitted * 1000 : now) / 1000 - started))
  return (
    <span className="clock" style={{ color: !run && sec > 25 * 60 ? 'var(--danger)' : undefined }}>
      <Timer size={16} />{Math.floor(sec / 60)}:{String(sec % 60).padStart(2, '0')}
    </span>
  )
}

export function Toasts({ items, onClose }) {
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} onClick={() => onClose(t.id)}>
          {t.kind === 'error' ? <AlertCircle size={16} className="st-flag" /> : <CheckCircle2 size={16} className="st-ok" />}
          {t.text}
        </div>
      ))}
    </div>
  )
}

const K = ({ k }) => k.split(' ').map((x) => <kbd key={x}>{x}</kbd>)

export function ShortcutsDialog({ assist, pilot, onClose }) {
  const groups = [
    ['Chỉnh cuboid đang chọn', [
      ['Dịch 10 cm (Shift: 50 cm)', 'W A S D'], ['Xoay 1° (Shift: 5°)', 'Q E'], ['Nâng / hạ 5 cm', 'R F'],
      ['Quay đầu 180°', 'T'], ['Xoá', 'Del'], ['Bỏ chọn / thoát công cụ', 'Esc'],
    ]],
    ['Công cụ', [
      ['Chọn', 'V'], ['Thêm cuboid (rồi bấm lên BEV)', 'B'], ['Căn giữa vào cuboid', 'C'], ['Bật / tắt xoay 3D', '3'],
    ]],
    ...(assist ? [['Trợ giúp 2D–3D', [
      ['Gợi ý cho mọi ô cam', 'Shift G'], ['Gợi ý cho cờ đang chọn', 'G'], ['Cờ tiếp / trước', 'N P'],
      ['Cờ đúng / báo động giả', '1 2'],
    ]]] : []),
    ['Chung', [
      ['Lưu', 'Ctrl S'], ['Hoàn tác / làm lại', 'Ctrl Z Ctrl Y'], ...(pilot ? [] : [['Frame trước / sau', '← →']]),
      ['Bảng phím tắt', '?'],
    ]],
  ]
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2><Keyboard size={18} /> Phím tắt <span className="grow" />
          <button className="icon-btn" onClick={onClose} aria-label="Đóng"><X size={16} /></button></h2>
        <div className="kgrid">
          {groups.map(([title, rows]) => (
            <div key={title} className="kgroup">
              <h4>{title}</h4>
              {rows.map(([what, k]) => <div key={what} className="krow"><span>{what}</span><span><K k={k} /></span></div>)}
            </div>
          ))}
        </div>
        <div className="kgroup">
          <h4>Chuột</h4>
          <div className="krow"><span>BEV: kéo thân / chấm trắng / chấm xanh của cuboid đang chọn</span><span>di chuyển · co giãn · xoay</span></div>
          <div className="krow"><span>Khung nhìn ngang: kéo cạnh / thân</span><span>cao · đáy · dài / rộng · nâng hạ</span></div>
          {assist && <div className="krow"><span>Ảnh: bấm ô cam · Shift+bấm box YOLO</span><span>gợi ý cuboid</span></div>}
          <div className="krow"><span>Lăn chuột · kéo nền</span><span>phóng to · di chuyển BEV</span></div>
        </div>
      </div>
    </div>
  )
}
