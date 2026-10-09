"""LiDAR and temporal QC on a synthetic organised sweep: flat ground, one car, a wall behind it.

  python tests/test_lidar_qc.py      (or pytest)
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from labeler import lidar_qc as lq  # noqa: E402
from labeler import track as tr  # noqa: E402
from labeler.propose import Sweep  # noqa: E402

GROUND = -1.84
CAR = {'box_id': 'car', 'cls': 'car', 'center': [12.0, 0.0, GROUND], 'size': [4.5, 1.9, 1.6], 'yaw': 0.0}


def _slab(o, d, lo, hi):
    with np.errstate(divide='ignore', invalid='ignore'):
        t1, t2 = (lo - o) / d, (hi - o) / d
    tn = np.max(np.minimum(t1, t2), axis=1)
    tf = np.min(np.maximum(t1, t2), axis=1)
    return np.where((tf > np.maximum(tn, 0)), tn, np.inf)


def synthetic_sweep(car=True) -> Sweep:
    """32 rings x 1086 columns like nuScenes LIDAR_TOP; empty shots are dummy points next to the sensor."""
    el = np.radians(np.linspace(-30.67, 10.67, 32))
    az = np.linspace(-np.pi, np.pi, 1086, endpoint=False)
    E, A = np.meshgrid(el, az)  # column-major order: point k = column k // 32, ring k % 32
    d = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], axis=-1).reshape(-1, 3)
    t = np.where(d[:, 2] < -1e-6, GROUND / np.where(d[:, 2] < -1e-6, d[:, 2], -1), np.inf)  # ground
    t = np.minimum(t, _slab(np.zeros(3), d, np.array([30.0, -40, GROUND]), np.array([31.0, 40, GROUND + 4])))  # wall
    if car:
        c = CAR['center']
        lo = np.array([c[0] - 2.25, c[1] - 0.95, GROUND + 0.2])
        t = np.minimum(t, _slab(np.zeros(3), d, lo, lo + [4.5, 1.9, 1.4]))
    t = np.where(t < 80, t, np.nan)
    pts = np.where(np.isfinite(t)[:, None], d * np.nan_to_num(t)[:, None], [0.001, -0.426, -0.028])
    ring = np.tile(np.arange(32), 1086)
    return Sweep(np.c_[pts, np.full(len(pts), 10.0), ring].astype(np.float32))


def test_ray_cast_hit_pass_occluded():
    sw = synthetic_sweep()
    on = lq.box_evidence(CAR, sw)['rays']
    assert on['hit'] > 50 and on['pass'] <= 0.1 * on['hit'], on
    # same cuboid moved 3 m sideways onto empty road: the shots go through to the wall
    off = lq.box_evidence({**CAR, 'center': [12.0, 3.0, GROUND]}, sw)['rays']
    assert off['hit'] <= 1 and off['pass'] > 20, off
    # a cuboid hidden right behind the car: its shots stop on the car (occluded), they are not evidence against it
    behind = lq.box_evidence({**CAR, 'box_id': 'b', 'center': [17.5, 0.0, GROUND], 'size': [4.0, 1.5, 1.2]}, sw)['rays']
    assert behind['occ'] > behind['pass'], behind


def test_flags():
    sw = synthetic_sweep()
    cfg = lq.load_cfg(Path('does-not-exist.json'))  # defaults, independent of the calibration
    cfg['size'] = {'car': {'l': [3.5, 5.5], 'w': [1.6, 2.2], 'h': [1.3, 2.0]}}
    fl, info = lq.lidar_check([CAR], sw, cfg)
    assert not fl and info['car']['checked'], fl
    ghost = {**CAR, 'box_id': 'ghost', 'center': [12.0, 3.5, GROUND]}
    types = {f['type'] for f in lq.lidar_check([ghost], sw, cfg)[0]}
    assert 'LIDAR_EMPTY' in types, types
    big = {**CAR, 'box_id': 'big', 'size': [7.2, 3.0, 2.6]}
    types = {f['type'] for f in lq.lidar_check([big], sw, cfg)[0]}
    assert 'SIZE_IMPLAUSIBLE' in types, types
    floating = {**CAR, 'box_id': 'up', 'center': [12.0, 0.0, GROUND + 0.8]}
    types = {f['type'] for f in lq.lidar_check([floating], sw, cfg)[0]}
    assert 'FLOATING' in types, types
    twin = {**CAR, 'box_id': 'twin', 'center': [12.5, 0.2, GROUND]}
    types = {f['type'] for f in lq.lidar_check([CAR, twin], sw, cfg)[0]}
    assert 'BEV_OVERLAP' in types, types


def _frame(t: float, x: float) -> dict:
    """Ego standing still at the origin; timestamps in microseconds."""
    return {'sample': f's{t}', 'timestamp': int(t * 1e6), 'lidar2global': np.eye(4).tolist()}


def test_track():
    cfg = dict(tr.DEFAULTS)
    obs_frames = []
    for k, t in enumerate((-1.0, -0.5, 0.5, 1.0)):  # a car driving at 10 m/s along x
        obs_frames.append((_frame(t, 0), [{**CAR, 'box_id': f'o{k}', 'instance': 'A', 'center': [12 + 10 * t, 0, GROUND]}]))
    cur = _frame(0.0, 0)
    good = {**CAR, 'instance': 'A'}
    fl, info = tr.track_check(cur, [good], obs_frames, {}, cfg)
    assert not fl and info['car']['n_obs'] == 4, (fl, info)
    for bad, want in (({**good, 'center': [13.5, 0, GROUND]}, 'TRACK_JUMP'),
                      ({**good, 'size': [6.5, 2.6, 2.2]}, 'TRACK_SIZE'),
                      ({**good, 'yaw': math.pi}, 'TRACK_YAW'),
                      ({**good, 'cls': 'truck'}, 'TRACK_CLASS')):
        types = {f['type'] for f in tr.track_check(cur, [bad], obs_frames, {}, cfg)[0]}
        assert want in types, (want, types)
    # without instance tokens the cuboids are linked by position
    drawn = {k: v for k, v in good.items() if k != 'instance'}
    plain = [(f, [{k: v for k, v in b.items() if k != 'instance'} for b in bs]) for f, bs in obs_frames]
    _, info = tr.track_check(cur, [drawn], plain, {}, cfg)
    assert info['car']['n_obs'] >= 2, info


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
