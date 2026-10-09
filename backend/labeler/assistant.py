"""Chat assistant: Claude explains M44 flags and proposes fixes, grounded in tools that read the current frame and
run the geometric fix engine (labeler/fix.py). Answers stream to the browser as server-sent events; every fix the
model proposes is also sent as a `suggestion` event so the UI can preview it and let the annotator apply it.

Credentials: the SDK's own lookup (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile); a
gitignored `.anthropic.env` next to the repo root is loaded into the environment at startup. Without credentials the
endpoint is off and the UI falls back to the offline suggestion cards.
"""
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from m44.geometry import project_frame
from m44.match import check

from .fix import points_inside, suggest

ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get('M44_LLM_MODEL', 'claude-opus-5-5')
EFFORT = os.environ.get('M44_LLM_EFFORT', 'low')  # chat: short grounded answers; raise for harder questions
MAX_TOOL_ROUNDS = 6
MAX_SESSIONS = 50

SYSTEM = """Bạn là trợ lý kiểm tra chất lượng (QC) trong M44 Labeler – công cụ gán nhãn cuboid 3D trên nuScenes. \
Người dùng là annotator người Việt; luôn trả lời bằng tiếng Việt, ngắn gọn (tối đa khoảng 5 câu hoặc vài gạch đầu dòng), \
thân thiện, đi thẳng vào việc cần làm.

Cách app hoạt động:
- Mỗi cuboid được chiếu lên 6 camera và so với vật YOLO phát hiện trên ảnh. Các loại cờ:
  LOW_IOU (lệch vị trí: hình chiếu ít trùng box YOLO), SIZE_MISMATCH (chiều cao/rộng hình chiếu khác box YOLO – sai \
kích thước hoặc sai hướng), CLASS_MISMATCH (class cuboid khác class YOLO), NO_2D_MATCH (cuboid không trùng vật nào \
trên ảnh – có thể cuboid thừa, đặt sai chỗ, hoặc vật bị che/tối/xa), MISSING_3D (YOLO thấy vật mà chưa có cuboid).
- Cuboid camera không kiểm được (bị che, xa, class YOLO không nhận) được kiểm bằng LiDAR (source "lidar"): LIDAR_EMPTY (tia LiDAR xuyên thẳng qua cuboid, gần như không chạm vật – cuboid thừa/dời chỗ), LIDAR_FREE (nhiều tia xuyên qua – cuboid lấn khoảng trống: quá to/lệch), LIDAR_SPILL (điểm của vật tràn ra ngoài – quá nhỏ/lệch), LIDAR_HEADING (trục dài đám điểm lệch hướng cuboid), SIZE_IMPLAUSIBLE (kích thước ngoài khoảng thường gặp của class), FLOATING/SUNKEN (đáy lơ lửng/chìm so với mặt đất), BEV_OVERLAP (hai cuboid chồng nhau). Tia bị vật khác chắn phía trước được tính là "bị che", không phải bằng chứng cuboid sai.
- Và bằng thời gian (source "track", so với chính vật đó ở các frame trước/sau): TRACK_SIZE (kích thước lệch trung vị chuỗi), TRACK_JUMP (vị trí lệch quỹ đạo), TRACK_YAW (hướng lệch, kể cả quay ngược 180°), TRACK_CLASS (class khác các frame khác). Mỗi cờ loại này có trường msg giải thích bằng số liệu.
- Mỗi cuboid có mức tin cậy QC: high (≥2 nguồn camera/LiDAR/thời gian xác nhận), medium (1 nguồn), none (chưa nguồn nào kiểm được), flagged (có cờ).
- Cờ là gợi ý, không phải phán quyết: YOLO có thể sai, vật có thể bị che. Annotator xác nhận bằng nút ✓ (đúng là lỗi) \
hoặc ✗ (báo động giả).
- Hệ toạ độ LiDAR: x hướng đầu xe ego, y sang trái, z lên. Cuboid: tâm đáy (x, y, z), kích thước dài × rộng × cao (m), \
hướng yaw. Luật chấm "đúng": tâm lệch ≤ 0,7 m, mỗi cạnh lệch ≤ 25 %, hướng lệch ≤ 20°.
- Phím tắt hữu ích: W A S D dịch, Q E xoay, R F nâng hạ, T quay đầu 180°, kéo cạnh ở khung nhìn ngang để chỉnh cao/dài.

Nguyên tắc:
- Không tự bịa số liệu. Dùng công cụ get_frame_overview / get_box_details để xem dữ liệu, và suggest_fix để tính \
cách sửa cụ thể. Khi đề xuất sửa một cờ, luôn gọi suggest_fix – giao diện sẽ hiện thẻ gợi ý có nút "Xem trước" và \
"Áp dụng" cho người dùng; bạn không tự áp dụng được.
- Giải thích ngắn vì sao có cờ dựa trên số liệu (IoU, số điểm LiDAR, kích thước so với cỡ điển hình), rồi nói nên làm gì.
- Nếu gợi ý là "dismiss" (báo động giả) hoặc có confidence "low" (chỉ dựa vào box YOLO, không có thêm bằng chứng LiDAR), nói rõ người dùng nên bấm "Xem trước" và nhìn ảnh để quyết định – đã có trường hợp cuboid đúng bị cờ do box YOLO lệch.
- Câu hỏi ngoài phạm vi gán nhãn: trả lời ngắn gọn hoặc lái về công việc."""

TOOLS = [
    {
        'name': 'get_frame_overview',
        'description': 'Tổng quan frame đang mở: số cuboid theo class, danh sách cờ hiện tại (flag_id, loại, cuboid, '
                       'camera, IoU), cuboid và cờ người dùng đang chọn.',
        'eager_input_streaming': True,
        'input_schema': {'type': 'object', 'properties': {}, 'required': []},
    },
    {
        'name': 'get_box_details',
        'description': 'Chi tiết một cuboid: class, tâm, kích thước, hướng, khoảng cách tới xe ego, số điểm LiDAR bên '
                       'trong, cỡ điển hình của class, các cờ đang có và hình chiếu trên từng camera.',
        'eager_input_streaming': True,
        'input_schema': {'type': 'object', 'properties': {'box_id': {'type': 'string'}}, 'required': ['box_id']},
    },
    {
        'name': 'suggest_fix',
        'description': 'Tính cách sửa cho một cờ bằng hình học (dời/xoay/co giãn khớp ảnh và điểm LiDAR, đổi class, '
                       'xoá cuboid thừa, tạo cuboid còn thiếu, hoặc khuyên đánh dấu báo động giả). Kết quả cũng hiện '
                       'thành thẻ có nút Áp dụng trên giao diện. Truyền flag_id (từ get_frame_overview).',
        'eager_input_streaming': True,
        'input_schema': {'type': 'object', 'properties': {'flag_id': {'type': 'string'}}, 'required': ['flag_id']},
    },
]


def _load_env_file() -> None:
    p = ROOT / '.anthropic.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


def available() -> tuple[bool, str]:
    """Whether credentials look configured (the first API call is the real test)."""
    _load_env_file()
    if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN') or os.environ.get('ANTHROPIC_PROFILE'):
        return True, ''
    if (Path.home() / '.config' / 'anthropic').exists():
        return True, ''
    return False, 'Chưa có khoá API Anthropic (ANTHROPIC_API_KEY, file .anthropic.env hoặc `ant auth login`).'


_client = None
_sessions: dict[str, list] = {}


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _sse(obj: dict) -> str:
    return f'data: {json.dumps(obj, ensure_ascii=False)}\n\n'


class Context:
    """What the tools see: the frame and the annotator's current (unsaved) cuboids, flags and selection."""

    def __init__(self, frame: dict, boxes: list[dict], dets: list[dict], sweep, cfg: dict,
                 selected: str | None, active_flag: dict | None, run: dict | None = None):
        """run: the full check result (camera + LiDAR + temporal flags, qc per cuboid) from main._run_check."""
        self.frame, self.boxes, self.dets, self.sweep, self.cfg = frame, boxes, dets, sweep, cfg
        self.selected, self.active_flag = selected, active_flag
        if run is None:
            run = {'flags': check(project_frame({**frame, 'boxes': boxes}), dets, cfg)[0], 'qc': {}, 'coverage': {}}
        self.flags, self.qc, self.coverage = run['flags'], run.get('qc', {}), run.get('coverage', {})

    def note(self) -> str:
        """One line of context prepended to each user message (volatile, so kept out of the cached system prompt)."""
        sel = next((b for b in self.boxes if b['box_id'] == self.selected), None)
        parts = [f"frame {self.frame['split']} {self.frame['split_index']}", f'{len(self.boxes)} cuboid', f'{len(self.flags)} cờ']
        if sel:
            parts.append(f"đang chọn cuboid {sel['box_id']} ({sel['cls']})")
        if self.active_flag:
            parts.append(f"cờ đang chọn {self._flag_ref(self.active_flag)} ({self.active_flag['type']}, "
                         f"{self.active_flag['cam']})")
        return '[Ngữ cảnh: ' + '; '.join(parts) + ']'

    def _flag_ref(self, f: dict) -> str:
        """Stable id the model can pass back: the index in self.flags of the same flag."""
        for k, g in enumerate(self.flags):
            if g['type'] == f['type'] and g.get('box_id') == f.get('box_id') and g['cam'] == f['cam'] \
                    and (f.get('box_id') or g.get('det_bbox') == f.get('det_bbox')):
                return f'F{k}'
        return 'F?'

    # ---------- tools ----------

    def overview(self) -> dict:
        by_cls: dict[str, int] = {}
        for b in self.boxes:
            by_cls[b['cls']] = by_cls.get(b['cls'], 0) + 1
        flags = [{'flag_id': f'F{k}', 'type': f['type'], 'source': f.get('source', 'camera'), 'box_id': f.get('box_id'),
                  'cls_3d': f.get('cls_3d'), 'cls_2d': f.get('cls_2d'), 'cam': f['cam'], 'iou': f.get('iou'),
                  **({'msg': f['msg']} if f.get('msg') else {})} for k, f in enumerate(self.flags)]
        levels: dict[str, int] = {}
        for q in self.qc.values():
            levels[q['level']] = levels.get(q['level'], 0) + 1
        return {'frame': f"{self.frame['split']} {self.frame['split_index']}", 'cuboids_by_class': by_cls,
                'qc_levels': levels, 'coverage_share': self.coverage,
                'n_yolo_detections': len(self.dets), 'flags': flags, 'selected_box': self.selected,
                'active_flag': self._flag_ref(self.active_flag) if self.active_flag else None}

    def box_details(self, box_id: str) -> dict:
        from m44.geometry import project_box

        from .propose import CLASS_SIZES
        b = next((x for x in self.boxes if x['box_id'] == box_id), None)
        if b is None:
            return {'error': f'không có cuboid {box_id}'}
        cams = {}
        for name, cam in self.frame['cams'].items():
            p = project_box(b, cam)
            if p:
                cams[name] = {'bbox_px': [round(v) for v in p['bbox']], 'depth_m': round(p['depth'], 1)}
        return {'box_id': box_id, 'cls': b['cls'], 'center_bottom_m': [round(v, 2) for v in b['center']],
                'size_lwh_m': [round(v, 2) for v in b['size']], 'yaw_deg': round(float(np.degrees(b['yaw'])), 1),
                'distance_m': round(float(np.hypot(*b['center'][:2])), 1),
                'lidar_points_inside': points_inside(self.sweep.nonground, b),
                'typical_size_lwh_m': list(CLASS_SIZES.get(b['cls'], [])),
                'flags': [{'flag_id': f'F{k}', 'type': f['type'], 'source': f.get('source', 'camera'), 'cam': f['cam'],
                           'iou': f.get('iou'), 'cls_2d': f.get('cls_2d'), **({'msg': f['msg']} if f.get('msg') else {})}
                          for k, f in enumerate(self.flags) if f.get('box_id') == box_id],
                'qc': {k: v for k, v in self.qc.get(box_id, {}).items() if k != 'pass_xy'},
                'visible_in_cameras': cams, 'source': b.get('source') or 'gt/manual'}

    def fix(self, flag_id: str) -> tuple[dict, dict | None]:
        try:
            flag = self.flags[int(flag_id.lstrip('Ff'))]
        except (ValueError, IndexError):
            return {'error': f'không có cờ {flag_id}; gọi get_frame_overview để lấy danh sách'}, None
        s = suggest(flag, self.boxes, self.frame, self.dets, self.sweep, self.cfg)
        s = {**s, 'id': uuid.uuid4().hex[:8],
             'flag': {k: flag.get(k) for k in ('type', 'box_id', 'cam', 'det_bbox', 'cls_2d', 'iou', 'source')}}
        return s, s

    def run(self, name: str, args) -> tuple[dict, dict | None, bool]:
        """(result, suggestion for the UI or None, is_error). Inputs are validated: with eager input streaming the
        server no longer checks them against the schema."""
        if not isinstance(args, dict):
            return {'error': 'INVALID_JSON'}, None, True
        if name == 'get_frame_overview':
            return self.overview(), None, False
        if name == 'get_box_details':
            if not isinstance(args.get('box_id'), str):
                return {'error': 'box_id (string) is required'}, None, True
            out = self.box_details(args['box_id'])
            return out, None, 'error' in out
        if name == 'suggest_fix':
            if not isinstance(args.get('flag_id'), str):
                return {'error': 'flag_id (string) is required'}, None, True
            out, s = self.fix(args['flag_id'])
            return out, s, 'error' in out
        return {'error': f'unknown tool {name}'}, None, True


def chat(session_id: str, text: str, ctx: Context) -> Iterator[str]:
    """Stream one assistant turn (possibly several tool rounds) as SSE lines."""
    import anthropic

    if session_id not in _sessions and len(_sessions) >= MAX_SESSIONS:
        _sessions.pop(next(iter(_sessions)))
    messages = _sessions.setdefault(session_id, [])
    messages.append({'role': 'user', 'content': f'{ctx.note()}\n\n{text}'})
    client = _get_client()
    json_retries = 0
    rounds = 0
    try:
        while rounds < MAX_TOOL_ROUNDS:
            try:
                with client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=16000,
                    system=[{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
                    tools=TOOLS,
                    messages=messages,
                    output_config={'effort': EFFORT},
                    # a policy decline is re-run server-side on the model Anthropic recommends for that category
                    betas=['server-side-fallback-2026-07-01'],
                    fallbacks='default',
                ) as stream:
                    for event in stream:
                        if event.type == 'text':
                            yield _sse({'type': 'text', 'text': event.text})
                    response = stream.get_final_message()
                json_retries = 0
            except ValueError:
                # tool input JSON the SDK could not parse at all: re-issue the turn (bounded)
                json_retries += 1
                if json_retries > 2:
                    raise
                continue

            # append-only history: the full content (thinking / fallback blocks included) goes back unchanged
            messages.append({'role': 'assistant', 'content': response.content})
            if response.stop_reason == 'refusal':
                yield _sse({'type': 'error', 'message': 'Claude từ chối yêu cầu này. Thử hỏi theo cách khác.'})
                break
            if response.stop_reason == 'pause_turn':
                continue
            tool_uses = [b for b in response.content if b.type == 'tool_use']
            if not tool_uses:
                break
            if response.stop_reason == 'max_tokens':
                yield _sse({'type': 'error', 'message': 'Câu trả lời bị cắt (quá dài).'})
                break
            results = []
            for tu in tool_uses:
                yield _sse({'type': 'tool', 'name': tu.name})
                out, suggestion, is_err = ctx.run(tu.name, tu.input)
                if suggestion is not None:
                    yield _sse({'type': 'suggestion', 'suggestion': suggestion})
                results.append({'type': 'tool_result', 'tool_use_id': tu.id, 'is_error': is_err,
                                'content': json.dumps(out, ensure_ascii=False, default=float)})
            messages.append({'role': 'user', 'content': results})  # all results of the turn in one message
            rounds += 1
    except anthropic.AuthenticationError:
        yield _sse({'type': 'error', 'message': 'Khoá API Anthropic không hợp lệ hoặc chưa cấu hình.'})
        _sessions.pop(session_id, None)
    except anthropic.PermissionDeniedError:
        yield _sse({'type': 'error', 'message': 'Khoá API không có quyền dùng model này.'})
    except anthropic.RateLimitError:
        yield _sse({'type': 'error', 'message': 'Đang bị giới hạn tốc độ, thử lại sau ít phút.'})
    except anthropic.APIStatusError as e:
        yield _sse({'type': 'error', 'message': f'Lỗi API ({e.status_code}). Thử lại sau.'})
    except anthropic.APIConnectionError:
        yield _sse({'type': 'error', 'message': 'Không kết nối được tới Anthropic (kiểm tra mạng).'})
    except ValueError:
        yield _sse({'type': 'error', 'message': 'Claude trả về dữ liệu công cụ hỏng nhiều lần, thử hỏi lại.'})
    yield _sse({'type': 'done'})


def reset(session_id: str) -> None:
    _sessions.pop(session_id, None)
