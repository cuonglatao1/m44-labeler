"""Fix suggestions for M44 flags: what to change on a flagged cuboid, with numbers the UI (or the chat
assistant) can show and apply.

  CLASS_MISMATCH  -> set the class the detector saw (COCO -> nuScenes)
  LOW_IOU,        -> search around the cuboid: shift (coarse ±2.5 m, then fine), turn (incl. ±90°), size (as is /
  SIZE_MISMATCH      class prior / ±10 %); score = 2D IoU with the matched YOLO box + share of the LiDAR points it
                     encloses - distance moved - departure from the class size; the 2D -> 3D proposal of the YOLO box
                     competes too. No clear gain -> suggest marking a false alarm.
  NO_2D_MATCH     -> almost no LiDAR points inside: a ghost cuboid, delete it; otherwise a real object the camera
                     did not see (occlusion, night, distance): mark a false alarm
  MISSING_3D      -> create the 2D -> 3D proposal of the YOLO box

Tuned on nuScenes-mini train with labeler/eval_fix.py (injected errors with known answers); see README for val.
"""
import math

import numpy as np

from m44.geometry import iou, project_box, project_frame
from m44.match import COMPATIBLE, check

from .propose import CLASS_SIZES, FROM_COCO, MIN_BATCH_FIT, Sweep, _frustum, propose

GHOST_POINTS = 3      # fewer LiDAR points than this inside a cuboid = nothing there
MIN_GAIN = 0.08       # 2D IoU gain needed before a geometric change is worth suggesting...
BIG_GAIN = 0.25       # ...unless it also encloses clearly more LiDAR points, this much gain alone is needed
                      # (a correct cuboid flagged because the YOLO box is loose already holds its points)
W_POINTS, W_MOVE, W_SIZE, W_YAW = 0.6, 0.12, 0.25, 0.001  # score weights (per unit / m / log size / degree)


def points_inside(pts: np.ndarray, box: dict, margin: float = 0.15) -> int:
    """LiDAR points (N x >=3, LiDAR frame) inside the cuboid grown by `margin`."""
    if not len(pts):
        return 0
    l, w, h = box['size']
    c, s = math.cos(box['yaw']), math.sin(box['yaw'])
    d = pts[:, :3] - np.asarray(box['center'])
    fx, fy = c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1]
    return int(((np.abs(fx) <= l / 2 + margin) & (np.abs(fy) <= w / 2 + margin)
                & (d[:, 2] >= -margin) & (d[:, 2] <= h + margin)).sum())


def _fit(box: dict, cam: dict, det) -> float:
    p = project_box(box, cam)
    return iou(p['bbox'], det) if p else 0.0


def _size_dev(box: dict) -> float:
    l0, w0, h0 = CLASS_SIZES.get(box['cls'], box['size'])
    return sum(abs(math.log(max(v, 0.05) / p)) for v, p in zip(box['size'], (l0, w0, h0))) / 3


def _local_pose(old: dict, new: dict) -> dict:
    """The change from `old` to `new` in the old cuboid's own axes (forward / left), metres and degrees."""
    c, s = math.cos(old['yaw']), math.sin(old['yaw'])
    dx, dy = new['center'][0] - old['center'][0], new['center'][1] - old['center'][1]
    dyaw = math.degrees((new['yaw'] - old['yaw'] + math.pi) % (2 * math.pi) - math.pi)
    return {'forward': round(c * dx + s * dy, 2), 'left': round(-s * dx + c * dy, 2),
            'up': round(new['center'][2] - old['center'][2], 2), 'yaw_deg': round(dyaw, 1),
            'size_from': [round(v, 2) for v in old['size']], 'size_to': [round(v, 2) for v in new['size']]}


def _describe(ch: dict) -> str:
    parts = []
    if abs(ch['forward']) >= 0.1:
        parts.append(f"dịch {abs(ch['forward']):.1f} m {'về trước' if ch['forward'] > 0 else 'ra sau'}")
    if abs(ch['left']) >= 0.1:
        parts.append(f"dịch {abs(ch['left']):.1f} m sang {'trái' if ch['left'] > 0 else 'phải'}")
    if abs(ch['up']) >= 0.1:
        parts.append(f"{'nâng' if ch['up'] > 0 else 'hạ'} {abs(ch['up']):.1f} m")
    if abs(ch['yaw_deg']) >= 2:
        parts.append(f"xoay {abs(ch['yaw_deg']):.0f}° {'ngược' if ch['yaw_deg'] > 0 else 'theo'} chiều kim đồng hồ")
    names = ('dài', 'rộng', 'cao')
    for k in range(3):
        a, b = ch['size_from'][k], ch['size_to'][k]
        if abs(b - a) >= 0.1 and abs(b / a - 1) >= 0.05:
            parts.append(f"{names[k]} {a:.2f} → {b:.2f} m")
    return ', '.join(parts) if parts else 'chỉnh rất nhỏ'


def refine_box(box: dict, cam: dict, det, sweep: Sweep, det_cls: str | None = None) -> tuple[dict, dict]:
    """Best nearby cuboid for one camera detection; returns (box, scores)."""
    # points of the detected object itself: the LiDAR returns inside the YOLO box's frustum near the cuboid (counting
    # every point around would pull the cuboid onto a neighbouring car or a wall)
    near = sweep.nonground[np.hypot(*(sweep.nonground[:, :2] - np.asarray(box['center'][:2])).T)
                           < max(box['size'][:2]) + 4.0]
    region = _frustum(near, cam, det)
    if len(region) < 5:
        region = near
    l0, w0, h0 = CLASS_SIZES.get(box['cls'], box['size'])

    def variants(b, offsets, yaws, sizes):
        for dx in offsets:
            for dy in offsets:
                for dyaw in yaws:
                    for size in sizes:
                        yield {**b, 'center': [b['center'][0] + dx, b['center'][1] + dy, b['center'][2]],
                               'yaw': b['yaw'] + math.radians(dyaw), 'size': list(size)}

    def score_all(cands):
        fits = [_fit(c, cam, det) for c in cands]
        pts = [points_inside(region, c) for c in cands]
        top = max(max(pts), 1)
        out = []
        for c, f, p in zip(cands, fits, pts):
            move = math.hypot(c['center'][0] - box['center'][0], c['center'][1] - box['center'][1])
            dyaw = abs(math.degrees((c['yaw'] - box['yaw'] + math.pi) % (2 * math.pi) - math.pi))
            sc = f + W_POINTS * p / top - W_MOVE * move - W_SIZE * _size_dev(c) - W_YAW * dyaw
            out.append((sc, f, p, c))
        return out

    coarse = np.arange(-2.5, 2.51, 0.5)
    sizes = [tuple(box['size']), (l0, w0, h0)]
    cands = list(variants(box, coarse, (0, -8, 8, 90, -90), sizes))
    p = propose(sweep, cam, det, det_cls or 'car')
    if p is not None:
        cands.append({**box, 'center': p['center'], 'size': p['size'], 'yaw': p['yaw']})
    best = max(score_all(cands), key=lambda t: t[0])[3]
    fine = np.arange(-0.4, 0.41, 0.1)
    bs = best['size']
    cands = list(variants(best, fine, (0, -3, 3, -6, 6), [tuple(bs), tuple(v * 0.9 for v in bs), tuple(v * 1.1 for v in bs)]))
    sc, fit, pts, best = max(score_all(cands), key=lambda t: t[0])
    return best, {'fit_iou': round(fit, 3), 'points': pts}


def _clean(box: dict) -> dict:
    return {k: (float(v) if isinstance(v, (np.floating, float)) else [float(x) for x in v] if isinstance(v, (list, tuple)) else v)
            for k, v in box.items()}


def suggest(flag: dict, boxes: list[dict], frame: dict, dets: list[dict], sweep: Sweep, cfg: dict) -> dict:
    """A suggestion for one flag: {action, summary, ...}. action: update | set_class | delete | create | dismiss | none."""
    if flag.get('source') in ('lidar', 'track'):  # LiDAR / temporal QC flags: labeler/fix_qc.py
        from .fix_qc import suggest_qc
        return suggest_qc(flag, boxes, sweep)
    by_id = {b['box_id']: b for b in boxes}
    box = by_id.get(flag.get('box_id'))
    cam = frame['cams'][flag['cam']]
    base = {'flag_type': flag['type'], 'box_id': flag.get('box_id'), 'cam': flag['cam']}

    if flag['type'] == 'MISSING_3D':
        p = propose(sweep, cam, flag['det_bbox'], flag['cls_2d'])
        if p is None or p['fit_iou'] < MIN_BATCH_FIT:
            return {**base, 'action': 'dismiss', 'summary': 'Không dựng được cuboid từ ảnh (vật quá xa hoặc không có điểm LiDAR). '
                    'Nếu vật thật sự có mặt thì vẽ tay; nếu YOLO nhận nhầm thì đánh dấu báo động giả.'}
        new = {'box_id': '_new', 'cls': p['cls'], 'center': p['center'], 'size': p['size'], 'yaw': p['yaw']}
        polished, sc = refine_box(new, cam, flag['det_bbox'], sweep, flag['cls_2d'])
        if sc['fit_iou'] >= p['fit_iou']:
            new = polished
            p = {**p, 'center': new['center'], 'size': new['size'], 'yaw': new['yaw'], 'fit_iou': sc['fit_iou']}
        new = {k: new[k] for k in ('cls', 'center', 'size', 'yaw')}
        how = f"{p['n_points']} điểm LiDAR" if p['method'] == 'lidar_cluster' else 'đặt theo mặt đất (ít điểm LiDAR)'
        return {**base, 'action': 'create', 'box': _clean(new), 'after': {'fit_iou': p['fit_iou'], 'points': p['n_points']},
                'summary': f"YOLO thấy một {flag['cls_2d']} chưa có cuboid. Tạo {p['cls']} {p['size'][0]:.1f}×{p['size'][1]:.1f}"
                           f"×{p['size'][2]:.1f} m ({how}, khớp ảnh {p['fit_iou']:.2f})."}

    if box is None:
        return {**base, 'action': 'none', 'summary': 'Cuboid của cờ này không còn trong frame.'}
    n_in = points_inside(sweep.nonground, box)
    n_all = points_inside(sweep.points[sweep.points[:, 2] > box['center'][2] + 0.1], box, margin=0.1)

    if flag['type'] == 'CLASS_MISMATCH':
        cls = FROM_COCO.get(flag['cls_2d'])
        if cls and cls != box['cls']:
            return {**base, 'action': 'set_class', 'cls': cls, 'before': {'cls': box['cls']},
                    'summary': f"Ảnh {flag['cam'].replace('CAM_', '')} cho thấy đây là {flag['cls_2d']} (IoU {flag['iou']:.2f}), "
                               f"không phải {box['cls']}. Đổi class sang {cls}."}
        return {**base, 'action': 'dismiss', 'summary': 'Class YOLO không quy đổi được sang class nuScenes; kiểm tra bằng mắt.'}

    if flag['type'] == 'NO_2D_MATCH':
        # a cuboid shifted off its object: the object's YOLO box is usually right next to the projection
        near = _nearby_det(box, cam, flag['cam'], dets)
        if near is not None:
            s = _update(base, box, boxes, frame, dets, sweep, cfg, cam, near['bbox'], near['cls'], n_in)
            if s['action'] == 'update':
                s['summary'] = f"Cuboid không trùng vật nào trên ảnh, nhưng ngay cạnh có một {near['cls']} YOLO thấy. " + s['summary']
                return s
        if n_all < GHOST_POINTS:
            return {**base, 'action': 'delete', 'before': {'points': n_all},
                    'summary': f"Chỉ có {n_all} điểm LiDAR trong cuboid và không camera nào thấy vật ở đó – nhiều khả năng là "
                               f"cuboid thừa (hoặc đặt sai chỗ hẳn). Nên xoá, hoặc kéo về đúng vật nếu bạn thấy nó."}
        return {**base, 'action': 'dismiss', 'before': {'points': n_all},
                'summary': f"Có {n_all} điểm LiDAR trong cuboid nên vật có thật; camera/YOLO không thấy có lẽ vì bị che, "
                           f"tối hoặc ở xa. Nếu nhìn ảnh thấy hợp lý thì đánh dấu báo động giả."}

    # LOW_IOU / SIZE_MISMATCH: geometric refinement against the matched YOLO box
    return _update(base, box, boxes, frame, dets, sweep, cfg, cam, flag['det_bbox'], flag.get('cls_2d'), n_in)


VEHICLES = {'car', 'truck', 'bus', 'trailer', 'construction_vehicle'}


def _same_kind(coco_cls: str, cls: str) -> bool:
    mapped = FROM_COCO.get(coco_cls)
    return mapped == cls or (mapped in VEHICLES and cls in VEHICLES and coco_cls in COMPATIBLE.get(cls, ()))


def _nearby_det(box: dict, cam: dict, cam_name: str, dets: list[dict]) -> dict | None:
    """YOLO box of the cuboid's own kind closest to its projection (overlapping or within 1.5 box sizes). Same kind
    is stricter than the checker's COMPATIBLE table: a bicycle must not be dragged onto the person standing next to it."""
    p = project_box(box, cam)
    if p is None:
        return None
    pb = p['bbox']
    pw, ph = pb[2] - pb[0], pb[3] - pb[1]
    pc = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2)
    best, best_d = None, None
    for d in dets:
        if d['cam'] != cam_name or not _same_kind(d['cls'], box['cls']):
            continue
        db = d['bbox']
        dist = math.hypot((db[0] + db[2]) / 2 - pc[0], (db[1] + db[3]) / 2 - pc[1]) / max(pw, ph, 1)
        if dist <= 1.5 and (best_d is None or dist < best_d):
            best, best_d = d, dist
    return best


def _update(base, box, boxes, frame, dets, sweep, cfg, cam, det, det_cls, n_in) -> dict:
    before_fit = _fit(box, cam, det)
    new, sc = refine_box(box, cam, det, sweep, det_cls)
    gain = sc['fit_iou'] - before_fit
    more_points = sc['points'] >= 1.2 * n_in + 3
    if gain < MIN_GAIN or (gain < BIG_GAIN and not more_points):
        return {**base, 'action': 'dismiss', 'before': {'fit_iou': round(before_fit, 3), 'points': n_in},
                'summary': f"Thử dời/xoay/co giãn quanh cuboid không khớp ảnh hơn đáng kể (IoU {before_fit:.2f} → "
                           f"{sc['fit_iou']:.2f}). Có thể box YOLO lệch (vật bị che một phần); nếu cuboid đã ôm đúng điểm "
                           f"LiDAR thì đánh dấu báo động giả."}
    # high confidence only with LiDAR evidence: a correct cuboid flagged because of a loose YOLO box already holds
    # its points, so a gain in 2D fit alone is a weaker signal
    confidence = 'high' if more_points else 'low'
    changes = _local_pose(box, new)
    others = [b if b['box_id'] != box['box_id'] else new for b in boxes]
    flags_after, _ = check(project_frame({**frame, 'boxes': others}), dets, cfg)
    left = sorted({f['type'] for f in flags_after if f.get('box_id') == box['box_id']})
    return {**base, 'action': 'update', 'confidence': confidence,
            'box': _clean({k: new[k] for k in ('center', 'size', 'yaw')}), 'changes': changes,
            'before': {'fit_iou': round(before_fit, 3), 'points': n_in}, 'after': {**sc, 'flags': left},
            'summary': f"{_describe(changes).capitalize()}. Khớp ảnh {before_fit:.2f} → {sc['fit_iou']:.2f}, "
                       f"điểm LiDAR trong cuboid {n_in} → {sc['points']}"
                       + ('; hết cờ.' if not left else f"; vẫn còn {', '.join(left)}.")
                       + ('' if confidence == 'high' else ' Lưu ý: cuboid hiện đã ôm gần đủ điểm LiDAR, gợi ý chủ yếu dựa '
                          'vào box YOLO – xem trước kỹ, nếu cuboid đang khớp điểm thì nên đánh dấu báo động giả.')}
