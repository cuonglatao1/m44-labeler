import { useEffect, useRef, useState } from 'react'
import {
  ArrowUp, Bot, Check, Eye, EyeOff, Loader2, MoveRight, PackagePlus, RotateCcw, ShieldX, Sparkles, Tag, Trash2,
  WifiOff, Wrench,
} from 'lucide-react'

const ACTION = {
  update: { icon: Wrench, title: 'Chỉnh cuboid', apply: 'Áp dụng' },
  set_class: { icon: Tag, title: 'Đổi class', apply: 'Đổi class' },
  delete: { icon: Trash2, title: 'Xoá cuboid thừa', apply: 'Xoá cuboid' },
  create: { icon: PackagePlus, title: 'Tạo cuboid còn thiếu', apply: 'Tạo cuboid' },
  dismiss: { icon: ShieldX, title: 'Có thể là báo động giả', apply: 'Đánh dấu báo động giả' },
  none: { icon: Sparkles, title: 'Không có gợi ý', apply: null },
}
const TOOL_LABEL = {
  get_frame_overview: 'Đang xem tổng quan frame', get_box_details: 'Đang xem chi tiết cuboid', suggest_fix: 'Đang tính cách sửa',
}

// minimal markdown: paragraphs, "- " bullets, **bold**
function Rich({ text }) {
  const blocks = []
  let list = null
  text.split('\n').forEach((line, i) => {
    const bold = (s) => s.split(/(\*\*[^*]+\*\*)/g).map((p, k) => (p.startsWith('**') && p.endsWith('**') ? <b key={k}>{p.slice(2, -2)}</b> : p))
    const m = line.match(/^\s*[-•*]\s+(.*)/)
    if (m) { (list ||= []).push(<li key={i}>{bold(m[1])}</li>); return }
    if (list) { blocks.push(<ul key={`u${i}`}>{list}</ul>); list = null }
    if (line.trim()) blocks.push(<p key={i}>{bold(line)}</p>)
  })
  if (list) blocks.push(<ul key="u-end">{list}</ul>)
  return <>{blocks}</>
}

// a fix for a flag from one source only (certainty 'review') is applied only after looking at it: blind application on
// a false alarm breaks the correct cuboid about 2 times in 3 (labeler/eval_lidar.py)
function SuggestionCard({ s, previewing, applied, onPreview, onApply }) {
  const a = ACTION[s.action] || ACTION.none
  const Icon = a.icon
  const canPreview = s.action === 'update' || s.action === 'create'
  const [looked, setLooked] = useState(false)
  const review = s.flag?.certainty === 'review'
  const locked = review && canPreview && !looked && !previewing
  const apply = () => {
    if (review && s.action === 'delete' && !window.confirm('Cờ này chỉ do một nguồn báo. Vẫn xoá cuboid? (Ctrl+Z để hoàn tác)')) return
    onApply()
  }
  return (
    <div className={`sugg ${s.action}`}>
      <div className="sugg-head"><span className="sugg-icon"><Icon size={14} /></span>{a.title}
        {s.confidence && <span className={`chip ${s.confidence === 'high' ? 'ok' : 'warn'}`} style={{ height: 20, fontSize: 11 }}>
          gợi ý {s.confidence === 'high' ? 'tin cậy cao' : 'tin cậy thấp'}</span>}
        {s.flag?.certainty && (
          <span className={`chip ${s.flag.certainty === 'high' ? 'danger' : ''}`} style={{ height: 20, fontSize: 11 }}
            title={s.flag.certainty === 'high' ? 'Cuboid bị từ 2 nguồn trở lên cùng gắn cờ' : 'Chỉ một nguồn gắn cờ'}>
            {s.flag.certainty === 'high' ? 'cờ chắc chắn' : 'cờ cần xem'}</span>
        )}
        {s.flag?.cam && <span className="sugg-cam">{s.flag.cam.replace('CAM_', '').replace('_', ' ')}</span>}</div>
      <div className="sugg-body">{s.summary}</div>
      {(s.before?.fit_iou != null || s.after?.fit_iou != null || s.after?.pass != null) && (
        <div className="sugg-metrics">
          {s.after?.fit_iou != null && (
            <span>Khớp ảnh {s.before?.fit_iou != null ? <>{s.before.fit_iou.toFixed(2)} <MoveRight size={11} /> </> : ''}<b>{s.after.fit_iou.toFixed(2)}</b></span>
          )}
          {s.after?.points != null && (
            <span>LiDAR {s.before?.points != null ? <>{s.before.points} <MoveRight size={11} /> </> : ''}<b>{s.after.points}</b> điểm</span>
          )}
          {s.after?.pass != null && (
            <span>Tia xuyên qua {s.before?.pass != null ? <>{s.before.pass} <MoveRight size={11} /> </> : ''}<b>{s.after.pass}</b></span>
          )}
        </div>
      )}
      {a.apply && (
        <div className="sugg-actions">
          {canPreview && !applied && (
            <button className={`btn sm ${locked ? 'pulse' : ''}`} onClick={() => { setLooked(true); onPreview() }}>
              {previewing ? <EyeOff size={13} /> : <Eye size={13} />}{previewing ? 'Ẩn xem trước' : 'Xem trước'}</button>
          )}
          <span className="grow" />
          {applied ? <span className="chip ok"><Check size={12} /> Đã áp dụng</span>
            : <button className="btn sm primary" onClick={apply} disabled={locked}
              title={locked ? 'Cờ một nguồn: bấm Xem trước để kiểm tra trên BEV và ảnh rồi mới áp dụng' : undefined}>{a.apply}</button>}
        </div>
      )}
    </div>
  )
}

export function AssistantPanel({ llm, messages, busy, onSend, onQuick, onReset, preview, applied, onPreview, onApply, hasFlag }) {
  const [text, setText] = useState('')
  const end = useRef(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }) }, [messages, busy])

  const send = () => {
    const t = text.trim()
    if (!t || busy || !llm.available) return
    setText('')
    onSend(t)
  }
  const quick = [
    ['fix', 'Gợi ý sửa cờ đang chọn', !hasFlag],
    ...(llm.available ? [['why', 'Vì sao có cờ này?', !hasFlag], ['scan', 'Frame này còn vấn đề gì?', false]] : []),
  ]

  return (
    <div className="assistant">
      <div className="asst-head">
        <span className="asst-avatar"><Bot size={15} /></span>
        <div className="asst-title">Trợ lý QC
          <small>{llm.available ? `Claude · ${llm.model}` : 'Chế độ offline – gợi ý tính sẵn'}</small>
        </div>
        <span className="grow" />
        <button className="icon-btn sm" onClick={onReset} title="Cuộc trò chuyện mới"><RotateCcw size={14} /></button>
      </div>

      <div className="asst-thread">
        {!messages.length && (
          <div className="asst-empty">
            <span className="empty-icon"><Sparkles size={22} style={{ color: '#a9c1ff' }} /></span>
            <b>Hỏi trợ lý về cờ đang chọn</b>
            <span>Chọn một cờ ở tab Kiểm tra (hoặc bấm <kbd>N</kbd>) – trợ lý giải thích vì sao bị cờ và đề xuất cách sửa, bạn xem trước rồi áp dụng.</span>
            {!llm.available && <span className="asst-offline"><WifiOff size={13} /> {llm.reason} Gợi ý hình học vẫn dùng được.</span>}
          </div>
        )}
        {messages.map((m) => (
          m.role === 'divider' ? <div key={m.id} className="asst-divider"><span>{m.text}</span></div> : (
            <div key={m.id} className={`msg ${m.role}`}>
              {m.role === 'bot' && <span className="asst-avatar sm"><Bot size={12} /></span>}
              <div className="msg-col">
                {(m.text || (m.role === 'bot' && !m.suggestions?.length && !m.error)) && (
                  <div className="bubble">{m.text ? <Rich text={m.text} /> : <span className="typing"><i /><i /><i /></span>}</div>
                )}
                {m.tools?.length > 0 && m.pending && (
                  <div className="tool-chip"><Loader2 size={12} className="spin" />{TOOL_LABEL[m.tools[m.tools.length - 1]] || 'Đang xử lý'}…</div>
                )}
                {m.suggestions?.map((s) => (
                  <SuggestionCard key={s.id} s={s} previewing={preview?.id === s.id} applied={applied.has(s.id)}
                    onPreview={() => onPreview(preview?.id === s.id ? null : s)} onApply={() => onApply(s)} />
                ))}
                {m.error && <div className="bubble error">{m.error}</div>}
              </div>
            </div>
          )
        ))}
        <div ref={end} />
      </div>

      <div className="asst-quick">
        {quick.map(([k, label, disabled]) => (
          <button key={k} className="quick-chip" disabled={disabled || busy} onClick={() => onQuick(k)}>
            <Sparkles size={12} />{label}
          </button>
        ))}
      </div>
      <div className={`asst-input ${llm.available ? '' : 'off'}`}>
        <textarea rows={1} value={text} disabled={!llm.available}
          placeholder={llm.available ? 'Hỏi về cuboid, cờ, cách sửa… (Enter để gửi)' : 'Thêm khoá API Anthropic để chat tự do'}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <button className="send" onClick={send} disabled={!text.trim() || busy || !llm.available} aria-label="Gửi">
          {busy ? <Loader2 size={15} className="spin" /> : <ArrowUp size={16} />}
        </button>
      </div>
    </div>
  )
}
