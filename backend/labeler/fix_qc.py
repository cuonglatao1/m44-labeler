"""Fix suggestions for the LiDAR and temporal QC flags (labeler/lidar_qc.py, labeler/track.py), same card format as
labeler/fix.py so the UI and the chat assistant show and apply them the same way.

  LIDAR_EMPTY        fit to the nearest object cluster without a cuboid (within 3 m), else delete
  LIDAR_FREE/SPILL/  fit the cuboid to its object's points (minimum-area rectangle grown to the class size on the side
  LIDAR_HEADING      the sensor cannot see; the length axis closest to the current heading unless the heading is wrong)
  SIZE_IMPLAUSIBLE   the size fits a class of another kind (car <-> pedestrian): change the class; else fit to the points
                     when there are enough, else the typical class size around the same center
  FLOATING/SUNKEN    put the bottom on the ground
  BEV_OVERLAP        the cuboid is provably empty (enough shots, no hits): delete it; otherwise look at both
  TRACK_SIZE         median size of the object over the other frames (face toward the sensor kept)
  TRACK_JUMP / YAW   pose predicted from the neighbouring frames
  TRACK_CLASS        the class of the object in most other frames
"""
import math

import numpy as np

from . import lidar_qc as lq
from .fix import _clean, _describe, _local_pose
from .propose import CLASS_SIZES, SMALL, Sweep, _clusters, _fit

_CFG = None


def _cfg() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = lq.load_cfg()
    return _CFG


def resize_keep_near(box: dict, size) -> dict:
    """New size, keeping the length / width faces that face the sensor (at the origin) where they are."""
    l, w, h = box['size']
    c, s = math.cos(box['yaw']), math.sin(box['yaw'])
    # sensor in the cuboid's axes
    ou, ov = -(c * box['center'][0] + s * box['center'][1]), -(-s * box['center'][0] + c * box['center'][1])
    du = (l - size[0]) / 2 * (1 if ou > 0 else -1)  # move the center toward the sensor when shrinking
    dv = (w - size[1]) / 2 * (1 if ov > 0 else -1)
    cx = box['center'][0] + c * du - s * dv
    cy = box['center'][1] + s * du + c * dv
    return {**box, 'center': [cx, cy, box['center'][2]], 'size': [float(v) for v in size]}


def resize_center(box: dict, size) -> dict:
    """New size around the same bottom center (no evidence of which face is wrong)."""
    return {**box, 'size': [float(v) for v in size]}


def _other_kind_class(box: dict) -> str | None:
    """A class of another kind (vehicle / person / two-wheeler / static) whose size range fits the cuboid, closest to
    its typical size first: a pedestrian drawn with a car's size is a class error, not a size error."""
    cfg = _cfg()
    fits = [c for c in cfg['size'] if lq.group(c) != lq.group(box['cls']) and c in CLASS_SIZES
            and not lq.size_outliers({**box, 'cls': c}, cfg)]
    if not fits:
        return None
    return min(fits, key=lambda c: sum(abs(math.log(v / p)) for v, p in zip(box['size'], CLASS_SIZES[c])))


def _object_points(box: dict, sweep: Sweep, search: float = 1.5) -> np.ndarray:
    """Non-ground points of the object the cuboid sits on: clusters around it that hold points inside the cuboid."""
    l, w, h = box['size']
    ng = sweep.nonground
    near = ng[np.hypot(ng[:, 0] - box['center'][0], ng[:, 1] - box['center'][1]) < max(l, w) / 2 + search]
    if len(near) < 3:
        return near[:0]
    loc = lq._local(near, box)
    inside = (np.abs(loc[:, 0]) <= l / 2 + 0.1) & (np.abs(loc[:, 1]) <= w / 2 + 0.1) & (loc[:, 2] >= -0.2) \
        & (loc[:, 2] <= h + 0.2)
    labels = _clusters(near, 0.3 if box['cls'] in SMALL else 0.4)
    counts = np.bincount(labels[inside], minlength=labels.max() + 1)
    return near[counts[labels] >= 3]


def _nearest_free_cluster(box: dict, boxes: list[dict], sweep: Sweep, radius: float = 3.0) -> np.ndarray:
    """Nearest object-sized cluster within `radius` of the cuboid that no other cuboid covers (for a shifted cuboid)."""
    ng = sweep.nonground
    near = ng[np.hypot(ng[:, 0] - box['center'][0], ng[:, 1] - box['center'][1]) < radius + max(box['size'][:2])]
    if len(near) < 5:
        return near[:0]
    labels = _clusters(near, 0.3 if box['cls'] in SMALL else 0.4)
    l0 = CLASS_SIZES.get(box['cls'], box['size'])[0]
    cands = []
    for k in np.unique(labels):
        pts = near[labels == k]
        if len(pts) < 8 or np.ptp(pts[:, :2], axis=0).max() > 1.2 * l0 + 0.5:  # too few / a wall or several objects
            continue
        mid = pts[:, :3].mean(axis=0)
        if any(b['box_id'] != box['box_id'] and lq._local(mid[None], b)[0, 0] ** 2 <= (b['size'][0] / 2 + 0.3) ** 2
               and lq._local(mid[None], b)[0, 1] ** 2 <= (b['size'][1] / 2 + 0.3) ** 2 for b in boxes):
            continue  # already boxed
        cands.append((float(np.hypot(mid[0] - box['center'][0], mid[1] - box['center'][1])), k))
    if not cands:
        return near[:0]
    return near[labels == min(cands)[1]]  # the nearest one: a shifted cuboid usually sits next to its object


def fit_to_points(box: dict, obj: np.ndarray, sweep: Sweep, keep_heading: bool = True) -> dict | None:
    """Cuboid fitted to an object's points; the candidate whose heading is closest to the current one (or, with
    keep_heading=False, the one whose length follows the points' long axis), the 180° choice kept from the cuboid."""
    if len(obj) < 5 or box['cls'] not in CLASS_SIZES:
        return None
    cands = _fit(obj, box['cls'], sweep.ground)
    l0, w0, _ = CLASS_SIZES[box['cls']]

    def cost(c):
        dyaw = lq._yaw_gap_deg(c['yaw'], box['yaw'])
        size = abs(math.log(c['size'][0] / l0)) + abs(math.log(c['size'][1] / w0))
        return (dyaw / 90 if keep_heading else 0) + size

    best = min(cands, key=cost)
    yaw = best['yaw']
    if box['cls'] not in SMALL and math.cos(yaw - box['yaw']) < 0:  # keep the cuboid's front
        yaw += math.pi
    if box['cls'] in SMALL:
        yaw = box['yaw']
    out = {**box, 'center': best['center'], 'size': best['size'], 'yaw': float(lq._wrap(yaw))}
    return None if lq.size_outliers(out, _cfg()) else out  # the points were not one object of this class


def slide_to_points(box: dict, boxes: list[dict], sweep: Sweep, reach: float = 3.0) -> dict | None:
    """The same cuboid (size, heading) moved within `reach` m onto object points: the best-filled positions on a 25 cm
    grid (a cost per metre moved, at least 1 m apart, never onto another cuboid) are judged by the LiDAR checks and
    the nearest one without a flag wins. None when no position holds 8 points and passes the checks."""
    l, w, h = box['size']
    ng = sweep.nonground
    r = reach + math.hypot(l, w) / 2 + 0.2
    near = ng[(np.abs(ng[:, 0] - box['center'][0]) < r) & (np.abs(ng[:, 1] - box['center'][1]) < r)]
    if len(near) < 8:
        return None
    loc = lq._local(near, box)  # move in the cuboid's own axes: a shift is a translation of the local points
    loc = loc[(loc[:, 2] >= -0.1) & (loc[:, 2] <= h + 0.1)]
    others = [b for b in boxes if b['box_id'] != box['box_id']
              and math.hypot(b['center'][0] - box['center'][0], b['center'][1] - box['center'][1]) < r + max(b['size'][:2])]
    c, s_ = math.cos(box['yaw']), math.sin(box['yaw'])
    cfg = _cfg()

    def moved(du, dv):
        return {**box, 'center': [box['center'][0] + c * du - s_ * dv, box['center'][1] + s_ * du + c * dv, box['center'][2]]}

    grid = []
    for du in np.arange(-reach, reach + 1e-6, 0.25):
        for dv in np.arange(-reach, reach + 1e-6, 0.25):
            n = int(((np.abs(loc[:, 0] - du) <= l / 2 + 0.1) & (np.abs(loc[:, 1] - dv) <= w / 2 + 0.1)).sum())
            if n >= 8 and math.hypot(du, dv) >= 0.25:
                grid.append((n - 2.0 * math.hypot(du, dv), float(du), float(dv), n))
    grid.sort(reverse=True)
    picked = []
    for sc, du, dv, n in grid:
        if len(picked) >= 20:
            break
        if any(math.hypot(du - p[1], dv - p[2]) < 1.0 for p in picked):
            continue
        cand = moved(du, dv)
        if any(lq.overlaps([cand, o], cfg['overlap']) for o in others):
            continue
        picked.append((sc, du, dv, cand))
    ok = [(math.hypot(du, dv), cand) for _, du, dv, cand in picked
          if not lq.judge(cand, lq.box_evidence(cand, sweep), cfg)[0]]
    return min(ok, key=lambda t: t[0])[1] if ok else None


def _evidence_line(box: dict, sweep: Sweep) -> dict:
    ev = lq.box_evidence(box, sweep)
    r = ev['rays'] or {}
    return {'points': ev['n_inside'], 'spill': ev['n_spill'], 'hit': r.get('hit', 0), 'pass': r.get('pass', 0)}


def _update(base: dict, box: dict, new: dict, sweep: Sweep, why: str, confidence: str = 'high') -> dict:
    ch = _local_pose(box, new)
    before, after = _evidence_line(box, sweep), _evidence_line(new, sweep)
    flags_after, _ = lq.judge(new, lq.box_evidence(new, sweep), _cfg())
    left = sorted({f['type'] for f in flags_after})
    return {**base, 'action': 'update', 'confidence': confidence,
            'box': _clean({k: new[k] for k in ('center', 'size', 'yaw')}), 'changes': ch,
            'before': before, 'after': {**after, 'flags': left},
            'summary': f"{why} {_describe(ch).capitalize()}. Điểm LiDAR trong cuboid {before['points']} → {after['points']}, "
                       f"tia xuyên qua {before['pass']} → {after['pass']}"
                       + ('; hết cờ LiDAR.' if not left else f"; vẫn còn {', '.join(left)}.")}


def suggest_qc(flag: dict, boxes: list[dict], sweep: Sweep) -> dict:
    by_id = {b['box_id']: b for b in boxes}
    box = by_id.get(flag.get('box_id'))
    base = {'flag_type': flag['type'], 'box_id': flag.get('box_id'), 'cam': flag.get('cam')}
    if box is None:
        return {**base, 'action': 'none', 'summary': 'Cuboid của cờ này không còn trong frame.'}
    t, d = flag['type'], flag.get('detail') or {}

    if t in ('FLOATING', 'SUNKEN'):
        new = {**box, 'center': [box['center'][0], box['center'][1], box['center'][2] - d['gap_m']]}
        return _update(base, box, new, sweep, 'Đặt đáy cuboid sát mặt đất.')

    if t == 'TRACK_SIZE':
        new = resize_center(box, d['med_size'])
        return _update(base, box, new, sweep, f"Lấy kích thước trung vị của vật này ở {d['n_obs']} frame khác.")
    if t == 'TRACK_JUMP':
        pc = d['pred_center']
        new = {**box, 'center': [pc[0], pc[1], pc[2]]}
        how = 'nội suy' if d.get('pred_kind') == 'interp' else 'ngoại suy'
        return _update(base, box, new, sweep, f'Đưa cuboid về vị trí {how} từ quỹ đạo ở các frame bên cạnh.',
                       'high' if d.get('pred_kind') == 'interp' else 'low')
    if t == 'TRACK_YAW':
        new = {**box, 'yaw': float(d['pred_yaw'])}
        return _update(base, box, new, sweep, 'Xoay theo hướng của vật ở các frame bên cạnh.')
    if t == 'TRACK_CLASS':
        return {**base, 'action': 'set_class', 'cls': d['major_cls'], 'before': {'cls': box['cls']},
                'summary': f"Ở {d['share']:.0%} các frame khác vật này là {d['major_cls']}. Đổi class sang {d['major_cls']}."}

    if t == 'BEV_OVERLAP':
        ev = _evidence_line(box, sweep)
        other = by_id.get(d.get('other_id'))
        if ev['hit'] <= 1 and ev['points'] < 3 and ev['hit'] + ev['pass'] >= _cfg()['empty_min_support']:
            return {**base, 'action': 'delete', 'before': {'points': ev['points']},
                    'summary': f"Cuboid này chồng lên {d.get('other_cls')} bên cạnh mà gần như không có điểm LiDAR "
                               f"({ev['points']} điểm) – nhiều khả năng là cuboid gán trùng. Nên xoá."}
        obj = _object_points(box, sweep, 0.5)
        new = fit_to_points(box, obj, sweep) if len(obj) >= 10 else None
        if new is not None and other is not None and not lq.overlaps([new, other], _cfg()['overlap']):
            return _update(base, box, new, sweep, 'Ôm lại đúng đám điểm của vật để tách khỏi cuboid bên cạnh.', 'low')
        return {**base, 'action': 'dismiss', 'before': {'points': ev['points']},
                'summary': 'Cả hai cuboid đều có điểm LiDAR. Xem ảnh: nếu là một vật gán hai lần thì xoá một cái; nếu là '
                           'hai vật sát nhau thì thu nhỏ cho khỏi chồng, hoặc đánh dấu báo động giả.'}

    if t == 'SIZE_IMPLAUSIBLE' and box['cls'] in CLASS_SIZES:
        other = _other_kind_class(box)
        if other:
            return {**base, 'action': 'set_class', 'cls': other, 'before': {'cls': box['cls']},
                    'summary': f"Cuboid {box['size'][0]:.1f}×{box['size'][1]:.1f}×{box['size'][2]:.1f} m quá khác cỡ "
                               f"{box['cls']} nhưng đúng cỡ {other} – nhiều khả năng gán nhầm class. Đổi sang {other} "
                               f"(nếu ảnh cho thấy đúng là {box['cls']} thì kéo lại kích thước)."}
        obj = _object_points(box, sweep)
        new = fit_to_points(box, obj, sweep) if len(obj) >= 15 else None
        if new is not None:
            return _update(base, box, new, sweep, f'Ôm theo {len(obj)} điểm LiDAR của vật.')
        new = resize_center(box, CLASS_SIZES[box['cls']])
        return _update(base, box, new, sweep, f"Ít điểm LiDAR: kéo về cỡ điển hình của {box['cls']} quanh tâm cũ.", 'low')

    if t in ('LIDAR_EMPTY', 'LIDAR_FREE', 'LIDAR_SPILL', 'LIDAR_HEADING'):
        # two candidates: the cuboid re-fitted to its object's points, and the same cuboid slid onto the points nearby
        # (LiDAR breaks a car at 15 m+ into several ring fragments, which the fit cannot always join); keep the one the
        # LiDAR checks like best
        obj = _nearest_free_cluster(box, boxes, sweep) if t == 'LIDAR_EMPTY' else _object_points(box, sweep)
        cands = []
        fit = fit_to_points(box, obj, sweep, keep_heading=t not in ('LIDAR_HEADING', 'LIDAR_EMPTY')) if len(obj) >= 8 else None
        if fit is not None:
            cands.append(('fit', fit))
        slid = slide_to_points(box, boxes, sweep)
        if slid is not None:
            cands.append(('slide', slid))
        if cands:
            def rank(c):
                ev = lq.box_evidence(c[1], sweep)
                fl, _ = lq.judge(c[1], ev, _cfg())
                return (len(fl), -ev['n_inside'])
            kind, new = min(cands, key=rank)
            ev_new = lq.box_evidence(new, sweep)
            if not lq.judge(new, ev_new, _cfg())[0] or t != 'LIDAR_EMPTY':
                why = {'LIDAR_EMPTY': 'Cuboid nằm lệch khỏi vật: đưa về đám điểm LiDAR gần nhất chưa có cuboid.',
                       'LIDAR_FREE': 'Thu / dời cuboid về đám điểm của vật.',
                       'LIDAR_SPILL': 'Nới / dời cuboid ôm hết đám điểm của vật.',
                       'LIDAR_HEADING': 'Xoay cuboid theo trục dài của đám điểm.'}[t]
                how = 'dựng lại theo điểm' if kind == 'fit' else 'giữ kích thước, trượt tới chỗ nhiều điểm nhất'
                return _update(base, box, new, sweep, f'{why} ({how}, {ev_new["n_inside"]} điểm)',
                               'high' if ev_new['n_inside'] >= 30 else 'low')
        if t == 'LIDAR_EMPTY':
            ev = _evidence_line(box, sweep)
            return {**base, 'action': 'delete', 'before': {'points': ev['points'], 'pass': ev['pass']},
                    'summary': f"{d.get('pass', ev['pass'])} tia LiDAR xuyên qua cuboid, xung quanh không có vật nào chưa "
                               f"gán – nhiều khả năng là cuboid thừa. Nên xoá (hoặc kéo về đúng vật nếu nhìn ảnh thấy nó)."}
        return {**base, 'action': 'dismiss',
                'summary': 'Quá ít điểm LiDAR để dựng lại cuboid. Xem ảnh và khung nhìn ngang; nếu cuboid hợp lý thì '
                           'đánh dấu báo động giả.'}

    return {**base, 'action': 'dismiss', 'summary': flag.get('msg', '')}
