"""Objects that should have a cuboid but have none ("forgot to label it"), found without the camera.

The camera check finds a missing cuboid only where YOLO sees the object (MISSING_3D). Two more sources here:

  TRACK_MISSING   the object has a cuboid in the keyframe before AND the keyframe after (≤ 1.1 s away, linked by object
                  id, or by position for cuboids without one), but no cuboid near the interpolated pose in this frame.
                  The interpolated cuboid is the suggested fix.
  LIDAR_UNBOXED   at that interpolated pose the LiDAR has object points (≥ missing_points above the ground): a second,
                  independent piece of evidence for the same missing object.

The LiDAR can also veto: when enough unoccluded shots reach the interpolated cuboid and almost none of them hit anything,
the object really is not there (it left the field, was a ghost in the neighbours), and no flag is raised.

All flags of one missing object share `group` ("miss:<object id>"), and a camera MISSING_3D whose YOLO box covers the
projection of the interpolated cuboid joins the group, so labeler/qc.py counts the agreeing sources (≥ 2 = sure).
"""
import math

import numpy as np

from m44.geometry import iou, project_box

from . import lidar_qc as lq
from .track import MAX_PRED_DT, _instance, _pose

DEFAULTS = {
    'missing_gate': {'vehicle': 1.5, 'pedestrian': 1.0, 'two_wheeler': 1.0, 'static': 0.8},  # m: a cuboid this close = present
    'missing_points': 5,        # LiDAR object points at the interpolated pose that count as evidence
    'missing_link_speed': {'vehicle': 15.0, 'pedestrian': 2.5, 'two_wheeler': 8.0, 'static': 0.5},  # m/s, linking by position
    'missing_cam_iou': 0.3,     # a YOLO box without cuboid this close to the projection is the same object
}


def _cfg(cfg: dict) -> dict:
    return {**DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS}}


def track_missing(frame: dict, boxes: list[dict], others: list[tuple[dict, list[dict]]], gt_instance: dict,
                  cfg: dict) -> list[dict]:
    """TRACK_MISSING flags (box_id None) with the interpolated cuboid in detail['box'].

    Objects with an id are looked up in every neighbouring keyframe within MAX_PRED_DT (the nearest appearance before
    and after counts, so the object may be missing in one neighbour too). Cuboids without an id are paired between the
    nearest keyframe before and after only, by position (same kind, within a speed gate, unambiguous).
    """
    c = _cfg(cfg)
    Li = np.linalg.inv(np.asarray(frame['lidar2global']))
    frames_dt = []
    for f, bs in others:
        dt = (f['timestamp'] - frame['timestamp']) / 1e6
        if 0 < abs(dt) <= MAX_PRED_DT:
            frames_dt.append((dt, f, bs))
    if not any(dt < 0 for dt, _, _ in frames_dt) or not any(dt > 0 for dt, _, _ in frames_dt):
        return []

    seen: dict[str, dict] = {}   # object id -> {'before': nearest obs, 'after': nearest obs}
    anon = {}                    # dt -> observations without an id, for the nearest frames only
    for dt, f, bs in frames_dt:
        T = Li @ np.asarray(f['lidar2global'])
        for b in bs:
            ctr, yaw = _pose(b, T)
            o = {'dt': dt, 'center': ctr, 'yaw': yaw, 'size': list(b['size']), 'cls': b['cls'],
                 'inst': _instance(b, gt_instance)}
            if o['inst']:
                side = 'before' if dt < 0 else 'after'
                cur = seen.setdefault(o['inst'], {})
                if side not in cur or abs(dt) < abs(cur[side]['dt']):
                    cur[side] = o
            else:
                anon.setdefault(dt, []).append(o)

    pairs = [(v['before'], v['after']) for v in seen.values() if 'before' in v and 'after' in v]
    dts_b = [dt for dt in anon if dt < 0]
    dts_a = [dt for dt in anon if dt > 0]
    if dts_b and dts_a:  # cuboids without an id: nearest frame before <-> nearest frame after, by position
        prev, nxt = anon[max(dts_b)], anon[min(dts_a)]
        span = min(dts_a) - max(dts_b)
        used = set()
        for o in prev:
            g = lq.group(o['cls'])
            gate = 1.0 + c['missing_link_speed'][g] * span
            cands = sorted((float(np.hypot(*(n['center'][:2] - o['center'][:2]))), k) for k, n in enumerate(nxt)
                           if lq.group(n['cls']) == g and k not in used)
            if cands and cands[0][0] <= gate and (len(cands) == 1 or cands[0][0] < 0.6 * cands[1][0]):
                used.add(cands[0][1])
                pairs.append((o, nxt[cands[0][1]]))

    have = {_instance(bx, gt_instance) for bx in boxes} - {None}
    no_id = [bx for bx in boxes if not _instance(bx, gt_instance)]
    flags = []
    for p0, n in pairs:
        if p0['cls'] != n['cls'] or (p0['inst'] and p0['inst'] in have):
            continue  # changed class (TRACK_CLASS's job) / boxed here, maybe elsewhere (TRACK_JUMP's job)
        k = (0 - p0['dt']) / (n['dt'] - p0['dt'])
        ctr = p0['center'] + k * (n['center'] - p0['center'])
        yaw = p0['yaw'] + k * lq._wrap(n['yaw'] - p0['yaw'])
        size = [(x + y) / 2 for x, y in zip(p0['size'], n['size'])]
        pred = {'cls': p0['cls'], 'center': [float(v) for v in ctr], 'size': size, 'yaw': float(lq._wrap(yaw)),
                'box_id': '_pred'}
        # boxed without an id (drawn by hand on the spot), or the same object boxed twice: nothing missing
        gate = c['missing_gate'][lq.group(p0['cls'])]
        if any(math.hypot(bx['center'][0] - ctr[0], bx['center'][1] - ctr[1]) < gate for bx in no_id) \
                or any(lq.overlaps([pred, bx], 0.5) for bx in boxes):
            continue
        inst = p0['inst'] or n['inst']
        dist = float(np.hypot(ctr[0], ctr[1]))
        flags.append({'type': 'TRACK_MISSING', 'box_id': None, 'cls_3d': p0['cls'],
                      'group': f"miss:{inst or f'{ctr[0]:.1f},{ctr[1]:.1f}'}",
                      'detail': {'box': {**{k2: pred[k2] for k2 in ('cls', 'center', 'size', 'yaw')}, 'instance': inst},
                                 'distance_m': round(dist, 1)},
                      'msg': f"Có một {p0['cls']} ở frame trước và frame sau nhưng frame này không có cuboid của nó "
                             f"(cách xe {dist:.0f} m) – nhiều khả năng bị quên gán. Gợi ý: tạo cuboid ở vị trí nội suy."})
    return flags


def corroborate(missing: list[dict], frame: dict, sweep, camera_flags: list[dict], lqc: dict) -> tuple[list[dict], list[dict]]:
    """(kept TRACK_MISSING flags, extra LIDAR_UNBOXED flags). Camera MISSING_3D flags on the same object get its group.

    sweep may be None (no LiDAR at hand): no veto, no LiDAR flag."""
    c = _cfg(lqc.get('track', {}) | lqc)
    kept, extra = [], []
    for f in missing:
        box = {**f['detail']['box'], 'box_id': '_pred'}
        if sweep is not None:
            ev = lq.box_evidence(box, sweep)
            rays = ev['rays'] or {}
            support = rays.get('hit', 0) + rays.get('pass', 0)
            f['detail']['points'] = ev['n_inside']
            f['detail']['rays'] = {k: v for k, v in rays.items() if k != 'pass_xy'}
            if support >= lqc['empty_min_support'] and rays.get('hit', 0) <= lqc['empty_max_hits'] \
                    and ev['n_body'] <= lqc['empty_max_hits'] + 1:
                continue  # the laser goes straight through: nothing there
            if ev['n_inside'] >= c['missing_points']:
                extra.append({'type': 'LIDAR_UNBOXED', 'box_id': None, 'cls_3d': f['cls_3d'], 'group': f['group'],
                              'detail': dict(f['detail']),
                              'msg': f"{ev['n_inside']} điểm LiDAR nằm ở chỗ vật này đáng lẽ phải có mà chưa có cuboid nào "
                                     f"– LiDAR xác nhận vật có thật."})
        kept.append(f)
        # camera: a YOLO box without cuboid on the projection of the interpolated cuboid is the same object
        for name, cam in frame['cams'].items():
            p = project_box(box, cam)
            if p is None:
                continue
            for g in camera_flags:
                if g['type'] == 'MISSING_3D' and g['cam'] == name and iou(p['bbox'], g['det_bbox']) >= c['missing_cam_iou']:
                    g['group'] = f['group']
                    g.setdefault('detail', {})['box'] = f['detail']['box']
    return kept, extra


def best_camera(box: dict, frame: dict):
    """(camera, projected bbox) where the cuboid projects biggest, or (None, None)."""
    best = (0.0, None, None)
    for name, cam in frame['cams'].items():
        p = project_box(box, cam)
        if p:
            a = (p['bbox'][2] - p['bbox'][0]) * (p['bbox'][3] - p['bbox'][1])
            if a > best[0]:
                best = (a, name, p['bbox'])
    return best[1], best[2]


def missing_hits(flags: list[dict], gt_box: dict, frame: dict, instance: str | None = None,
                 dist: float = 1.5) -> tuple[set, bool]:
    """Evaluation: which sources flagged the deleted cuboid `gt_box` as missing, and whether one of those flags is sure.
    camera = a MISSING_3D whose YOLO box covers its projection (IoU >= 0.3, as m44.evaluate); track / lidar = a
    TRACK_MISSING / LIDAR_UNBOXED for the same object id or within `dist` m of it."""
    srcs, sure = set(), False
    proj = {name: project_box(gt_box, cam) for name, cam in frame['cams'].items()}
    for f in flags:
        hit = False
        if f['type'] == 'MISSING_3D':
            p = proj.get(f['cam'])
            hit = p is not None and iou(p['bbox'], f['det_bbox']) >= 0.3
        elif f['type'] in ('TRACK_MISSING', 'LIDAR_UNBOXED'):
            b = f['detail']['box']
            hit = (instance is not None and b.get('instance') == instance) or \
                math.hypot(b['center'][0] - gt_box['center'][0], b['center'][1] - gt_box['center'][1]) <= dist
        if hit:
            srcs.add(f.get('source', 'camera'))
            sure = sure or f.get('certainty') == 'high'
    return srcs, sure
