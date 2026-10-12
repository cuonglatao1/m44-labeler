"""Temporal QC: the same object across the keyframes of a scene must keep its size and class and move smoothly.
This is the strongest evidence for an occluded cuboid: borrow it from the frames where the object is seen clearly.

Objects are linked by the nuScenes instance token (GT cuboids, and cuboids edited from them keep their box_id); cuboids
drawn in the app are linked to the nearest cuboid of the same kind in the neighbouring frames after ego-motion
compensation (every frame carries its LiDAR -> global pose).

  TRACK_SIZE   l, w or h differs from the median of the other frames by more than the threshold
  TRACK_JUMP   center off the position predicted from the neighbouring frames (interpolated from the frames
               before and after, or extrapolated from two frames on one side – the best prediction counts, so one
               wrong neighbour does not raise a flag on a correct cuboid)
  TRACK_YAW    heading off the predicted one (vehicles and two-wheelers; catches 180° flips the cameras cannot see)
  TRACK_CLASS  class differs from the class the object has in most other frames
  TRACK_HEIGHT bottom off the predicted height (a cuboid raised / sunk while its neighbours sit on the ground)

Each flag carries the corrected value (median size / predicted pose / majority class) for the fix suggestion.
Thresholds: configs/lidar_qc.json key "track" (labeler/calib_lidar.py, percentiles of clean train GT).
"""
import math
from collections import Counter

import numpy as np

from .lidar_qc import TWO_WHEEL, VEHICLES, _wrap, group

K_FRAMES = 4         # keyframes before / after that are looked at (nuScenes: 2 Hz -> 2 s)
MAX_PRED_DT = 1.1    # s: neighbours farther than this do not predict the pose
DEFAULTS = {
    'min_obs': 2,
    'size_dev': 0.1,       # |log(size / track median)| (0.1 = 10 %)
    'jump_m': {'vehicle': 0.8, 'pedestrian': 0.6, 'two_wheeler': 0.8, 'static': 0.4},
    'extrap_scale': 2.0,   # an extrapolated prediction is this much less precise than an interpolated one
    'yaw_deg': 25.0,
    'class_share': 0.7,
    'z_m': {'vehicle': 0.2, 'pedestrian': 0.2, 'two_wheeler': 0.2, 'static': 0.2},  # TRACK_HEIGHT
}


def _thr(v, g: str) -> float:
    """A threshold given for every class group ({group: value}) or as one number."""
    return v[g] if isinstance(v, dict) else v


def _pose(box: dict, T: np.ndarray) -> tuple[np.ndarray, float]:
    c = T[:3, :3] @ np.asarray(box['center'], dtype=float) + T[:3, 3]
    return c, float(box['yaw'] + math.atan2(T[1, 0], T[0, 0]))


def _instance(b: dict, gt_instance: dict) -> str | None:
    return b.get('instance') or gt_instance.get(b['box_id'])


def observations(frame: dict, boxes: list[dict], others: list[tuple[dict, list[dict]]], gt_instance: dict) -> dict:
    """box_id -> observations of the same object in the other frames, in this frame's LiDAR axes:
    [{dt (s), center, yaw, size, cls}] sorted by dt."""
    Li = np.linalg.inv(np.asarray(frame['lidar2global']))
    t0 = frame['timestamp']
    prepared = []
    for fj, bj in others:
        T = Li @ np.asarray(fj['lidar2global'])
        dt = (fj['timestamp'] - t0) / 1e6
        items = []
        for b in bj:
            c, yaw = _pose(b, T)
            items.append({'dt': dt, 'center': c, 'yaw': yaw, 'size': list(b['size']), 'cls': b['cls'],
                          'inst': _instance(b, gt_instance), 'box_id': b['box_id']})
        prepared.append((dt, items))
    prepared.sort(key=lambda x: abs(x[0]))

    out = {}
    for b in boxes:
        inst = _instance(b, gt_instance)
        obs = []
        if inst:
            for _, items in prepared:
                obs += [o for o in items if o['inst'] == inst]
        else:  # drawn in the app: nearest cuboid of the same kind, chained outwards from this frame
            pos, g = np.asarray(b['center'], dtype=float), group(b['cls'])
            last = {-1: (0.0, pos), 1: (0.0, pos)}
            vel = {-1: None, 1: None}
            for dt, items in prepared:
                side = 1 if dt > 0 else -1
                t_prev, p_prev = last[side]
                pred = p_prev + (vel[side] * (dt - t_prev) if vel[side] is not None else 0)
                # first step: anything up to the class's top speed (m/s); once the velocity is known, only its change
                speed = 3.0 if vel[side] is not None else {'pedestrian': 2.5, 'static': 0.5}.get(g, 15.0)
                gate = (1.0 if g in ('pedestrian', 'static') else 1.5) + speed * abs(dt - t_prev)
                cands = sorted(((float(np.hypot(*(o['center'][:2] - pred[:2]))), k) for k, o in enumerate(items)
                                if group(o['cls']) == g), key=lambda x: x[0])
                if not cands or cands[0][0] > gate or (len(cands) > 1 and cands[0][0] > 0.6 * cands[1][0]):
                    continue
                o = items[cands[0][1]]
                if t_prev != dt:
                    vel[side] = (o['center'] - p_prev) / (dt - t_prev) if abs(dt - t_prev) > 1e-3 else None
                last[side] = (dt, o['center'])
                obs.append(o)
        out[b['box_id']] = sorted(obs, key=lambda o: o['dt'])
    return out


def _predictions(obs: list[dict]) -> list[tuple[np.ndarray, float, float]]:
    """(center, yaw, scale) predicted at dt = 0: interpolation between the nearest frames before and after (scale 1),
    extrapolation from the two nearest frames on one side (scale extrap_scale, applied by the caller)."""
    before = [o for o in obs if -MAX_PRED_DT <= o['dt'] < 0][::-1]
    after = [o for o in obs if 0 < o['dt'] <= MAX_PRED_DT]
    preds = []

    def lerp(a, b, t):  # value at time 0 on the line through a (time ta) and b (time tb)
        k = (0 - a['dt']) / (b['dt'] - a['dt'])
        c = a['center'] + k * (b['center'] - a['center'])
        y = a['yaw'] + k * _wrap(b['yaw'] - a['yaw'])
        return c, float(y), t

    if before and after:
        preds.append(lerp(before[0], after[0], 'interp'))
    if len(before) >= 2:
        preds.append(lerp(before[1], before[0], 'extrap'))
    if len(after) >= 2:
        preds.append(lerp(after[0], after[1], 'extrap'))
    return preds


def track_stats(box: dict, obs: list[dict], cfg: dict) -> dict:
    """Numbers behind the temporal checks for one cuboid."""
    st = {'n_obs': len(obs)}
    if len(obs) < cfg['min_obs']:
        return st
    med = np.median([o['size'] for o in obs], axis=0)
    dev = np.abs(np.log(np.maximum(box['size'], 0.05) / np.maximum(med, 0.05)))
    st['med_size'] = [round(float(v), 2) for v in med]
    st['size_dev'] = round(float(dev.max()), 3)
    cls_count = Counter(o['cls'] for o in obs)
    major, n_major = cls_count.most_common(1)[0]
    st['major_cls'], st['major_share'] = major, round(n_major / len(obs), 2)
    preds = _predictions(obs)
    if preds:
        cur = np.asarray(box['center'], dtype=float)
        # the best prediction counts (one wrong neighbour spoils the predictions through it, not the others); with
        # only extrapolations the tolerance grows by extrap_scale. jump / yaw_gap are compared with the thresholds,
        # jump_raw / yaw_raw are the real distance / angle shown to the annotator
        scale = 1.0 if any(kind == 'interp' for _, _, kind in preds) else cfg['extrap_scale']
        best = min(preds, key=lambda p: float(np.hypot(*(cur[:2] - p[0][:2]))))
        raw = float(np.hypot(*(cur[:2] - best[0][:2])))
        st.update({'jump': round(raw / scale, 2), 'jump_raw': round(raw, 2),
                   'pred_center': [round(float(v), 3) for v in best[0]], 'pred_kind': best[2]})
        by = min(preds, key=lambda p: abs(_wrap(box['yaw'] - p[1])))
        raw_yaw = abs(math.degrees(_wrap(box['yaw'] - by[1])))
        st['yaw_gap'], st['yaw_raw'], st['pred_yaw'] = round(raw_yaw / scale, 1), round(raw_yaw, 1), round(float(by[1]), 4)
        bz = min(preds, key=lambda p: abs(cur[2] - p[0][2]))
        raw_z = float(cur[2] - bz[0][2])
        st['z_gap'], st['z_raw'], st['pred_z'] = round(abs(raw_z) / scale, 3), round(raw_z, 2), round(float(bz[0][2]), 3)
    return st


def judge(box: dict, st: dict, cfg: dict) -> tuple[list[dict], bool]:
    if st['n_obs'] < cfg['min_obs']:
        return [], False
    g = group(box['cls'])
    flags = []
    if st['size_dev'] > _thr(cfg['size_dev'], g):
        m = st['med_size']
        flags.append({'type': 'TRACK_SIZE', 'detail': {'dev': st['size_dev'], 'med_size': m, 'n_obs': st['n_obs']},
                      'msg': f"Kích thước {box['size'][0]:.2f}×{box['size'][1]:.2f}×{box['size'][2]:.2f} m lệch "
                             f"{math.expm1(st['size_dev']):.0%} so với chính vật này ở {st['n_obs']} frame khác "
                             f"(trung vị {m[0]:.2f}×{m[1]:.2f}×{m[2]:.2f} m)."})
    if 'jump' in st and st['jump'] > cfg['jump_m'][g]:
        how = 'nội suy từ frame trước và sau' if st['pred_kind'] == 'interp' else 'ngoại suy từ 2 frame cùng phía'
        flags.append({'type': 'TRACK_JUMP', 'detail': {'jump_m': st['jump_raw'], 'pred_center': st['pred_center'],
                                                        'pred_kind': st['pred_kind']},
                      'msg': f"Vị trí lệch {st['jump_raw']:.1f} m so với quỹ đạo của vật ({how}) – cuboid bị dời nhầm."})
    if (box['cls'] in VEHICLES or box['cls'] in TWO_WHEEL) and 'yaw_gap' in st and st['yaw_gap'] > _thr(cfg['yaw_deg'], g):
        flags.append({'type': 'TRACK_YAW', 'detail': {'gap_deg': st['yaw_raw'], 'pred_yaw': st['pred_yaw']},
                      'msg': f"Hướng lệch {st['yaw_raw']:.0f}° so với hướng của vật ở các frame bên cạnh"
                             + (' – có thể bị quay ngược đầu.' if st['yaw_raw'] > 150 else '.')})
    if 'z_gap' in st and st['z_gap'] > _thr(cfg.get('z_m', DEFAULTS['z_m']), g):
        up = st['z_raw'] > 0
        flags.append({'type': 'TRACK_HEIGHT', 'detail': {'dz_m': st['z_raw'], 'pred_z': st['pred_z']},
                      'msg': f"Đáy cuboid {'cao' if up else 'thấp'} hơn {abs(st['z_raw']):.2f} m so với chính vật này ở các "
                             f"frame bên cạnh – cuboid bị {'nâng lên' if up else 'hạ xuống'} nhầm."})
    if st['major_cls'] != box['cls'] and st['major_share'] >= cfg['class_share'] and st['n_obs'] >= cfg['min_obs']:
        flags.append({'type': 'TRACK_CLASS', 'detail': {'major_cls': st['major_cls'], 'share': st['major_share']},
                      'msg': f"Vật này là {st['major_cls']} ở {st['major_share']:.0%} các frame khác, ở đây lại là {box['cls']}."})
    return flags, True


def track_check(frame: dict, boxes: list[dict], others: list[tuple[dict, list[dict]]], gt_instance: dict,
                cfg: dict) -> tuple[list[dict], dict]:
    """(flags, stats per box_id)."""
    obs = observations(frame, boxes, others, gt_instance)
    flags, info = [], {}
    for b in boxes:
        st = track_stats(b, obs[b['box_id']], cfg)
        fl, checked = judge(b, st, cfg)
        info[b['box_id']] = {'checked': checked, **st}
        flags += [{**f, 'box_id': b['box_id'], 'cls_3d': b['cls']} for f in fl]
    return flags, info
