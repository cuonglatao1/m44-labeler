"""Copy the cuboids of the previous keyframe into the current one ("propagate"), keeping each object's id.

  pose      LiDAR(prev) -> global -> LiDAR(cur): the ego car's own motion is compensated exactly
  motion    with the keyframe before that, the object's velocity and turn rate (both in the current frame's axes)
            push it forward to the current time; without, it stays where it was (parked cars, standing people)
  snap      (off by default) slide the copy ≤ 1 m onto clearly more LiDAR points. Measured on train it makes copies
            worse at every threshold tried (97 % -> 91-96 % correct): a cuboid hugs the whole object while the points
            sit on the faces the sensor sees, so the snap pulls a well-predicted cuboid toward the sensor

Each copy keeps `instance`, so the temporal check links it to the same object in every frame even for cuboids drawn in
the app (no nuScenes instance token). Objects already boxed in the current frame (same instance, or a cuboid on the same
spot) are not copied again.

Measured with labeler/eval_propagate.py.
"""
import math
import uuid

import numpy as np

from . import lidar_qc as lq
from .propose import Sweep, box_overlaps

SNAP_REACH = 1.0     # m
SNAP_STEP = 0.1      # m
SNAP_COST = 3.0      # points per metre moved
SNAP_GAIN = 1.2      # the snapped position must hold this many times the points ...
SNAP_MIN_GAIN = 5    # ... and at least this many more
MAX_DT = 1.1         # s: an older keyframe farther back than this does not give a velocity
MAX_SPEED = 25.0     # m/s: faster = two different objects behind the same id, ignore


def new_instance() -> str:
    """Object id for a cuboid drawn in the app (GT cuboids keep their nuScenes instance token)."""
    return f'obj_{uuid.uuid4().hex[:10]}'


def _to(frame_to: dict, frame_from: dict) -> np.ndarray:
    """4x4 transform LiDAR(frame_from) -> LiDAR(frame_to)."""
    return np.linalg.inv(np.asarray(frame_to['lidar2global'])) @ np.asarray(frame_from['lidar2global'])


def _pose(box: dict, T: np.ndarray) -> tuple[np.ndarray, float]:
    c = T[:3, :3] @ np.asarray(box['center'], dtype=float) + T[:3, 3]
    return c, float(box['yaw'] + math.atan2(T[1, 0], T[0, 0]))


def snap(box: dict, sweep: Sweep, reach: float = SNAP_REACH) -> tuple[dict, int, float]:
    """(cuboid, points inside, metres moved): moved onto clearly more object points, else unchanged."""
    l, w, h = box['size']
    ng = sweep.nonground
    r = reach + math.hypot(l, w) / 2 + 0.2
    near = ng[(np.abs(ng[:, 0] - box['center'][0]) < r) & (np.abs(ng[:, 1] - box['center'][1]) < r)]
    loc = lq._local(near, box)
    loc = loc[(loc[:, 2] >= -0.1) & (loc[:, 2] <= h + 0.1)]

    def count(du, dv):
        return int(((np.abs(loc[:, 0] - du) <= l / 2 + 0.1) & (np.abs(loc[:, 1] - dv) <= w / 2 + 0.1)).sum())

    n0 = count(0.0, 0.0)
    best = (n0, 0.0, 0.0, n0)
    steps = np.arange(-reach, reach + 1e-6, SNAP_STEP)
    for du in steps:
        for dv in steps:
            d = math.hypot(du, dv)
            if d > reach or d < 1e-6:
                continue
            n = count(du, dv)
            if n - SNAP_COST * d > best[0]:
                best = (n - SNAP_COST * d, float(du), float(dv), n)
    _, du, dv, n = best
    if (du or dv) and n >= SNAP_GAIN * n0 and n >= n0 + SNAP_MIN_GAIN:
        c, s = math.cos(box['yaw']), math.sin(box['yaw'])
        moved = {**box, 'center': [box['center'][0] + c * du - s * dv, box['center'][1] + s * du + c * dv,
                                   box['center'][2]]}
        return moved, n, math.hypot(du, dv)
    return box, n0, 0.0


def dismissed_types(prev_boxes: list[dict], feedback: dict[str, str], gt_instance: dict | None = None) -> dict:
    """{object id: flag types the reviewer marked false alarm (✗) on it in that frame}, including the ones it already
    carried over from earlier frames, minus the ones confirmed (✓) there."""
    gt_instance = gt_instance or {}
    inst_of = {b['box_id']: b.get('instance') or gt_instance.get(b['box_id']) for b in prev_boxes}
    out: dict[str, set] = {}
    for b in prev_boxes:
        carried = (b.get('propagated') or {}).get('dismissed') or []
        if carried and inst_of[b['box_id']]:
            out.setdefault(inst_of[b['box_id']], set()).update(carried)
    for key, verdict in feedback.items():  # key: TYPE|box_id|cam or source|...
        ftype, box_id = key.split('|')[:2]
        i = inst_of.get(box_id)
        if not i:
            continue
        if verdict == 'false_alarm':
            out.setdefault(i, set()).add(ftype)
        elif verdict == 'accept':
            out.get(i, set()).discard(ftype)
    return out


def propagate(cur: dict, prev: tuple[dict, list[dict]], older: tuple[dict, list[dict]] | None,
              existing: list[dict], sweep: Sweep | None, gt_instance: dict | None = None,
              use_motion: bool = True, use_snap: bool = False,
              dismissed: dict | None = None) -> tuple[list[dict], dict]:
    """New cuboids for frame `cur` from the cuboids of keyframe `prev` (and `older` for velocities).

    Returns (cuboids, stats). Every cuboid gets a fresh box_id and keeps (or receives) its object id in `instance`;
    `propagated` records where it came from, how far the snap moved it, and (`dismissed`, from dismissed_types) the flag
    types already judged false alarms on this object, so the same occlusion does not ask the reviewer again.
    """
    gt_instance = gt_instance or {}
    inst = lambda b: b.get('instance') or gt_instance.get(b['box_id'])  # noqa: E731
    f_prev, prev_boxes = prev
    T = _to(cur, f_prev)
    dt = (cur['timestamp'] - f_prev['timestamp']) / 1e6
    older_pose = {}
    if older and use_motion:
        f_old, old_boxes = older
        dt_old = (f_prev['timestamp'] - f_old['timestamp']) / 1e6
        if 0 < dt_old <= MAX_DT:
            T_old = _to(cur, f_old)
            for b in old_boxes:
                if inst(b):
                    older_pose[inst(b)] = (_pose(b, T_old), dt_old)

    have = {inst(b) for b in existing if inst(b)}
    out, stats = [], {'from': len(prev_boxes), 'copied': 0, 'skipped_existing': 0, 'with_motion': 0, 'snapped': 0}
    for b in prev_boxes:
        i = inst(b) or new_instance()
        if i in have:
            stats['skipped_existing'] += 1
            continue
        c, yaw = _pose(b, T)
        if i in older_pose:
            (c_old, yaw_old), dt_old = older_pose[i]
            v = (c - c_old) / dt_old
            if np.hypot(v[0], v[1]) <= MAX_SPEED:
                c = c + v * dt
                c[2] = _pose(b, T)[0][2]  # height does not drift
                yaw = yaw + lq._wrap(yaw - yaw_old) / dt_old * dt
                stats['with_motion'] += 1
        nb = {'box_id': f'prop_{cur["sample"][:6]}_{uuid.uuid4().hex[:6]}', 'cls': b['cls'],
              'center': [float(v) for v in c], 'size': [float(v) for v in b['size']], 'yaw': float(lq._wrap(yaw)),
              'visibility': None, 'num_lidar_pts': None, 'instance': i, 'source': 'propagated'}
        if box_overlaps(nb, existing, min_dist=0.8):  # this object is already boxed (without the same id)
            stats['skipped_existing'] += 1
            continue
        moved, n_pts = 0.0, None
        if use_snap and sweep is not None:
            nb, n_pts, moved = snap(nb, sweep)
            stats['snapped'] += moved > 0
        nb['num_lidar_pts'] = n_pts
        nb['propagated'] = {'from': f_prev['sample'], 'moved': round(moved, 2), 'points': n_pts,
                            'motion': i in older_pose, 'dismissed': sorted((dismissed or {}).get(i, ()))}
        out.append(nb)
    stats['copied'] = len(out)
    return out, stats
