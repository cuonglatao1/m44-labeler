"""LiDAR QC: checks for the cuboids the cameras cannot verify (occluded, far, classes YOLO does not know), from the
point cloud alone.

nuScenes LIDAR_TOP sweeps are stored as an organised range image: 32 rings x ~1086 azimuth columns, point k is
column k // 32, ring k % 32, and a slot without a return holds a dummy point next to the sensor. So every laser shot
is known – the ones that came back empty too – and a cuboid can be ray-cast against the shots that were really fired:

  every shot whose ray crosses the cuboid (shrunk a little, lifted off the ground):
    return well before the cuboid  -> occluded (something in front of it)
    return inside the cuboid       -> hit
    return well behind the cuboid  -> pass: the laser went straight through where the cuboid claims an object
    no return                      -> unknown

The shots that reach the cuboid unoccluded (hit + pass = support) are the occlusion-aware "expected points". Most of
them passing through = an empty cuboid (ghost, misplaced); a large share passing = the cuboid covers free space (too
big, shifted). Further checks:

  SIZE_IMPLAUSIBLE  l, w or h outside the range of that class in train GT
  FLOATING/SUNKEN   bottom far above / below the ground around the cuboid
  BEV_OVERLAP       two cuboids sharing their footprint
  LIDAR_SPILL       points of the object (connected to the cuboid's own points) outside the cuboid: too small / shifted
  LIDAR_HEADING     long axis of the object's points vs the cuboid's heading (vehicles seen along their length)

Thresholds: configs/lidar_qc.json, written by `python -m labeler.calib_lidar --split train` (percentiles of clean
train GT, so each check fires on roughly 0.5 % of correct cuboids).
"""
import json
import math
import warnings
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

from m44.geometry import box_corners

from .propose import CLASS_SIZES, SMALL, Sweep, _clusters, _min_area_yaw

ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / 'configs' / 'lidar_qc.json'

N_RINGS = 32
MIN_RANGE = 2.5     # m: the dummy "no return" points and the ego car itself are closer than this
GAP = 0.3           # m: a return this far before the entry / after the exit of a cuboid is occluded / passing
WINDOW = math.radians(1.0)  # angular margin around a cuboid when picking the shots to ray-cast
VEHICLES = {'car', 'truck', 'bus', 'trailer', 'construction_vehicle'}
STATIC = {'barrier', 'traffic_cone'}
TWO_WHEEL = {'bicycle', 'motorcycle'}
CACHE_MAX = 4000

# fallback thresholds when configs/lidar_qc.json is missing (calib_lidar writes the real ones)
DEFAULTS = {
    'min_support': 6,          # shots reaching the cuboid unoccluded before the ray checks judge it
    'empty_max_hits': 1,       # LIDAR_EMPTY: at most this many hits ...
    'empty_min_support': 6,    # ... with at least this support
    # per class group [minimum evidence, threshold]:
    'free': {'vehicle': [10, 0.55], 'pedestrian': [10, 0.75], 'two_wheeler': [10, 0.75], 'static': [10, 0.8]},
    #   LIDAR_FREE: [support, share of passing shots]
    'spill': {'vehicle': [5, 0.3], 'pedestrian': [8, 0.5], 'two_wheeler': [8, 0.5], 'static': [8, 0.6]},
    #   LIDAR_SPILL: [spilled points, spilled share]
    'heading': {'vehicle': [30, 30], 'pedestrian': [50, 60], 'two_wheeler': [50, 60], 'static': [50, 60]},
    #   LIDAR_HEADING: [object points, degrees]
    'ground': {'vehicle': [-0.45, 0.45], 'pedestrian': [-0.45, 0.45], 'two_wheeler': [-0.45, 0.45],
               'static': [-0.45, 0.45]},  # FLOATING / SUNKEN: bottom - ground (m)
    'overlap': 0.3,            # BEV_OVERLAP: intersection / smaller footprint
    'size': {},                # {cls: {"l": [lo, hi], "w": .., "h": ..}}
    'size_margin': 1.05,
}


def group(cls: str) -> str:
    if cls in VEHICLES:
        return 'vehicle'
    if cls in TWO_WHEEL:
        return 'two_wheeler'
    if cls in STATIC:
        return 'static'
    return 'pedestrian'


def load_cfg(path: Path = CFG_PATH) -> dict:
    """LiDAR thresholds, with the temporal ones under "track"."""
    from .track import DEFAULTS as TRACK_DEFAULTS

    cfg = dict(DEFAULTS)
    file = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    cfg.update({k: v for k, v in file.items() if not k.startswith('_')})
    cfg['track'] = {**TRACK_DEFAULTS, **file.get('track', {})}
    return cfg


def _wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


# ---------- range image + ray casting ----------

class RangeImage:
    """Every laser shot of a sweep: direction (unit vector) and range of the first return (inf = no return)."""

    def __init__(self, pts: np.ndarray):
        n = len(pts)
        xyz = pts[:, :3].astype(np.float64)
        rng = np.linalg.norm(xyz, axis=1)
        valid = rng > MIN_RANGE
        ring = pts[:, 4].astype(np.int64) if pts.shape[1] >= 5 else None
        organised = ring is not None and n % N_RINGS == 0 and np.array_equal(ring, np.arange(n) % N_RINGS)
        if organised:
            cols = n // N_RINGS
            self.range = np.where(valid, rng, np.inf).reshape(cols, N_RINGS).T.copy()
            xyz = xyz.reshape(cols, N_RINGS, 3).transpose(1, 0, 2)
            valid = valid.reshape(cols, N_RINGS).T
        else:
            # other sensors: bin the returns by ring (or elevation) and azimuth, keep the nearest per cell
            cols = 1086
            az = np.arctan2(xyz[:, 1], xyz[:, 0])
            if ring is None:
                el = np.arctan2(xyz[:, 2], np.hypot(xyz[:, 0], xyz[:, 1]))
                ring = np.clip(((el + math.radians(31)) / math.radians(42) * N_RINGS).astype(np.int64), 0, N_RINGS - 1)
            c = np.floor((az + np.pi) / (2 * np.pi) * cols).astype(np.int64) % cols
            self.range = np.full((N_RINGS, cols), np.inf)
            np.minimum.at(self.range, (ring[valid], c[valid]), rng[valid])
            grid = np.zeros((N_RINGS, cols, 3))
            grid[ring[valid], c[valid]] = xyz[valid]
            xyz, valid = grid, np.isfinite(self.range)
        safe = np.where(valid[..., None], xyz, np.nan)
        el = np.arctan2(safe[..., 2], np.hypot(safe[..., 0], safe[..., 1]))
        az = np.arctan2(safe[..., 1], safe[..., 0])
        # nominal direction of every shot (for the empty ones): the ring's elevation, the column's azimuth
        with np.errstate(all='ignore'), warnings.catch_warnings():  # rings / columns without any return
            warnings.simplefilter('ignore', RuntimeWarning)
            self.el_ring = np.nanmedian(el, axis=1)
            col_az = np.angle(np.nansum(np.exp(1j * np.nan_to_num(az, nan=0.0)) * valid, axis=0))
        has = valid.any(axis=0)
        if not has.all():  # columns without any return: interpolate the azimuth
            k = np.arange(cols)
            col_az = np.interp(k, k[has], np.unwrap(col_az[has]), period=cols) if has.any() else \
                -np.pi + 2 * np.pi * (k + 0.5) / cols
            col_az = _wrap(col_az)
        self.el_ring = np.where(np.isfinite(self.el_ring), self.el_ring,
                                np.interp(np.arange(N_RINGS), np.flatnonzero(np.isfinite(self.el_ring)),
                                          self.el_ring[np.isfinite(self.el_ring)]))
        self.col_az = col_az
        nominal = np.stack([np.cos(self.el_ring)[:, None] * np.cos(col_az)[None],
                            np.cos(self.el_ring)[:, None] * np.sin(col_az)[None],
                            np.repeat(np.sin(self.el_ring)[:, None], cols, axis=1)], axis=-1)
        with np.errstate(invalid='ignore', divide='ignore'):
            actual = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
        self.dirs = np.where(valid[..., None], actual, nominal)

    def cast(self, box: dict) -> dict | None:
        """Shots crossing the cuboid, classified hit / pass / occluded / unknown; None when the sensor is inside it."""
        cx, cy, cz = box['center']
        l, w, h = box['size']
        c, s = math.cos(box['yaw']), math.sin(box['yaw'])
        # sensor (origin) in the cuboid's own axes
        ou, ov = -(c * cx + s * cy), -(-s * cx + c * cy)
        if abs(ou) < l / 2 + 0.3 and abs(ov) < w / 2 + 0.3:
            return None
        lift = 0.15 if box['cls'] in SMALL else 0.35  # pedestrians' legs / the gap under a car: not judged
        if h <= lift + 0.1:
            lift = 0.0
        # angular window of the cuboid
        corners = box_corners(box['center'], box['size'], box['yaw'])
        a0 = math.atan2(cy, cx)
        rel = _wrap(np.arctan2(corners[:, 1], corners[:, 0]) - a0)
        rho_min = math.hypot(max(abs(ou) - l / 2, 0.0), max(abs(ov) - w / 2, 0.0))
        rho = np.hypot(corners[:, 0], corners[:, 1])
        zs = np.array([cz + lift, cz + h])
        els = np.concatenate([np.arctan2(corners[:, 2], rho), np.arctan2(zs, max(rho_min, 0.1))])
        cols = np.flatnonzero((_wrap(self.col_az - a0) >= rel.min() - WINDOW) & (_wrap(self.col_az - a0) <= rel.max() + WINDOW))
        rings = np.flatnonzero((self.el_ring >= els.min() - WINDOW) & (self.el_ring <= els.max() + WINDOW))
        if not len(cols) or not len(rings):
            return {'rays': 0, 'hit': 0, 'pass': 0, 'occ': 0, 'none': 0}
        d = self.dirs[np.ix_(rings, cols)].reshape(-1, 3)
        r = self.range[np.ix_(rings, cols)].reshape(-1)
        # ray directions in the cuboid's axes (z unchanged)
        du, dv, dz = c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1], d[:, 2]
        o = (ou, ov, -cz)

        def slab(half_l, half_w, z_lo, z_hi):
            tn, tf = np.zeros(len(d)), np.full(len(d), np.inf)
            for oo, dd, lo, hi in ((o[0], du, -half_l, half_l), (o[1], dv, -half_w, half_w), (o[2], dz, z_lo, z_hi)):
                with np.errstate(divide='ignore', invalid='ignore'):
                    t1, t2 = (lo - oo) / dd, (hi - oo) / dd
                par = np.abs(dd) < 1e-12  # parallel to the slab: inside it or never
                inside = (oo >= lo) & (oo <= hi)
                t1 = np.where(par, np.where(inside, -np.inf, np.inf), t1)
                t2 = np.where(par, np.where(inside, np.inf, -np.inf), t2)
                tn, tf = np.maximum(tn, np.minimum(t1, t2)), np.minimum(tf, np.maximum(t1, t2))
            return tn, tf

        # shots through the shrunk cuboid (grazing shots along the silhouette say little; a person or a bike fills only
        # the middle of its cuboid, arms and legs leave gaps) ...
        if box['cls'] in SMALL:
            sl, sw = 0.3 * l, 0.3 * w
        else:
            sl, sw = min(0.15, 0.1 * l), min(0.15, 0.1 * w)
        tn_in, tf_in = slab(l / 2 - sl, w / 2 - sw, lift + 0.05, h - 0.05)
        crossing = tf_in - tn_in > 0.1
        # ... are judged against the full one
        tn, tf = slab(l / 2, w / 2, lift, h)
        tn, tf, r = tn[crossing], tf[crossing], r[crossing]
        known = np.isfinite(r)
        occ = known & (r < tn - GAP)
        pas = known & (r > tf + GAP)
        hit = known & ~occ & ~pas
        out = {'rays': int(crossing.sum()), 'hit': int(hit.sum()), 'pass': int(pas.sum()), 'occ': int(occ.sum()),
               'none': int((~known).sum())}
        # where the passing shots leave the cuboid (drawn in the BEV): LiDAR frame x, y
        if out['pass']:
            dd = d[crossing][pas]
            p = dd * tf[pas, None]
            out['pass_xy'] = np.round(p[:40, :2], 2).tolist()
        return out


def range_image(sweep: Sweep) -> RangeImage | None:
    if 'rimg' not in sweep.qc_cache:
        sweep.qc_cache['rimg'] = RangeImage(sweep.raw) if sweep.raw.shape[1] >= 5 else None
    return sweep.qc_cache['rimg']


# ---------- per-cuboid evidence ----------

def _local(pts: np.ndarray, box: dict) -> np.ndarray:
    c, s = math.cos(box['yaw']), math.sin(box['yaw'])
    d = pts[:, :3] - np.asarray(box['center'])
    return np.stack([c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1], d[:, 2]], axis=1)


def _points_evidence(box: dict, sweep: Sweep) -> dict:
    """Object points around the cuboid: how many inside, how many of the same object outside (spill), the object's
    long axis."""
    l, w, h = box['size']
    small = box['cls'] in SMALL
    grow = 0.6 if small else 1.0
    ng = sweep.nonground
    near = ng[(np.abs(ng[:, 0] - box['center'][0]) < l + w + 2) & (np.abs(ng[:, 1] - box['center'][1]) < l + w + 2)]
    loc = _local(near, box)
    shell = (np.abs(loc[:, 0]) <= l / 2 + grow) & (np.abs(loc[:, 1]) <= w / 2 + grow) \
        & (loc[:, 2] >= -0.3) & (loc[:, 2] <= h + 0.3)
    pts, loc = near[shell], loc[shell]
    m = 0.1
    inside = (np.abs(loc[:, 0]) <= l / 2 + m) & (np.abs(loc[:, 1]) <= w / 2 + m) & (loc[:, 2] >= -m) & (loc[:, 2] <= h + m)
    n_in = int(inside.sum())
    out = {'n_inside': n_in, 'n_spill': 0, 'spill_out_m': 0.0}
    if n_in < 3:
        return out
    labels = _clusters(pts, 0.3 if small else 0.4)
    counts = np.bincount(labels[inside], minlength=labels.max() + 1)
    own = counts[labels] >= 3  # clusters holding at least 3 of the cuboid's points
    spill = own & ~inside
    out['n_spill'] = int(spill.sum())
    if out['n_spill']:
        # how far the spilled points stick out (90th percentile, m)
        ex = np.maximum(np.abs(loc[spill, 0]) - l / 2, 0)
        ey = np.maximum(np.abs(loc[spill, 1]) - w / 2, 0)
        out['spill_out_m'] = round(float(np.percentile(np.hypot(ex, ey), 90)), 2)
    obj = pts[own]
    if box['cls'] in VEHICLES and len(obj) >= 10:
        xy = obj[:, :2]
        yaw0 = _min_area_yaw(xy)
        ext = []
        for a in (yaw0, yaw0 + np.pi / 2):
            ext.append(float(np.ptp(xy @ [math.cos(a), math.sin(a)])))
        long_axis = yaw0 if ext[0] >= ext[1] else yaw0 + np.pi / 2
        out['axis'] = {'yaw': float(long_axis), 'long': round(max(ext), 2), 'short': round(min(ext), 2),
                       'n': int(len(obj))}
    return out


GROUND_RING = 2.0   # m around the footprint where the ground is measured
GROUND_MIN_PTS = 8  # flat low returns needed to trust the ground height
GROUND_WINDOW = 1.0  # m: only returns this close in height to the cuboid bottom can be its ground (gaps up to 1 m)


def _ground_gap(box: dict, sweep: Sweep) -> float | None:
    """Cuboid bottom minus the ground around its footprint, None when the ground there is not seen.

    Ground = the low, flat returns within GROUND_RING m of the footprint (outside the cuboid): the 5th percentile of z,
    trusted only when enough returns lie within 15 cm of it and they spread over a metre or more (the lower edge of a
    car door alone is not ground).
    """
    l, w, h = box['size']
    pts = sweep.points
    cx, cy = box['center'][:2]
    r = math.hypot(l, w) / 2 + GROUND_RING
    near = pts[(np.abs(pts[:, 0] - cx) < r) & (np.abs(pts[:, 1] - cy) < r)
               & (np.abs(pts[:, 2] - box['center'][2]) < GROUND_WINDOW)]  # not a road on another level
    near = near[np.linalg.norm(near[:, :3], axis=1) > MIN_RANGE]
    loc = _local(near, box)
    ring = (np.abs(loc[:, 0]) <= l / 2 + GROUND_RING) & (np.abs(loc[:, 1]) <= w / 2 + GROUND_RING) \
        & ~((np.abs(loc[:, 0]) <= l / 2 + 0.2) & (np.abs(loc[:, 1]) <= w / 2 + 0.2)) & (loc[:, 2] < h)
    z = near[ring, 2]
    if len(z) < GROUND_MIN_PTS:
        return None
    g = float(np.percentile(z, 5))
    flat = near[ring][z < g + 0.15]
    if len(flat) < GROUND_MIN_PTS or np.ptp(flat[:, :2], axis=0).max() < 1.0:
        return None
    g = float(np.median(flat[:, 2]))
    # the ground cannot be higher than the lowest return under the cuboid (with the real ground hidden behind other
    # cars, the "flat" returns around can be a neighbour's roof)
    under = (np.abs(loc[:, 0]) <= l / 2) & (np.abs(loc[:, 1]) <= w / 2) & (loc[:, 2] < h)
    if under.sum() >= 3:
        g = min(g, float(np.percentile(near[under, 2], 2)) + 0.1)
    return round(float(box['center'][2] - g), 2)


def _body_points(box: dict, sweep: Sweep) -> int:
    """Returns inside the cuboid from 12 cm above its bottom: a dark or glassy car can let most shots through and give
    returns only from its lower body, which the ray check (lifted off the ground) does not count as hits."""
    l, w, h = box['size']
    pts = sweep.points
    r = math.hypot(l, w) / 2 + 0.2
    near = pts[(np.abs(pts[:, 0] - box['center'][0]) < r) & (np.abs(pts[:, 1] - box['center'][1]) < r)]
    loc = _local(near, box)
    return int(((np.abs(loc[:, 0]) <= l / 2 + 0.1) & (np.abs(loc[:, 1]) <= w / 2 + 0.1)
                & (loc[:, 2] >= 0.12) & (loc[:, 2] <= h + 0.1)).sum())


def box_evidence(box: dict, sweep: Sweep) -> dict:
    """Everything the LiDAR says about one cuboid (cached per geometry: the live check re-runs on every edit)."""
    key = (box['cls'], *np.round(box['center'], 3), *np.round(box['size'], 3), round(box['yaw'], 4))
    cache = sweep.qc_cache.setdefault('boxes', {})
    if key in cache:
        return cache[key]
    rimg = range_image(sweep)
    ev = {'rays': rimg.cast(box) if rimg is not None else None, **_points_evidence(box, sweep),
          'ground_gap': _ground_gap(box, sweep), 'n_body': _body_points(box, sweep)}
    if len(cache) > CACHE_MAX:
        cache.clear()
    cache[key] = ev
    return ev


# ---------- checks ----------

def _footprint(b: dict) -> Polygon:
    return Polygon(box_corners(b['center'], b['size'], b['yaw'])[:4, :2])


def overlaps(boxes: list[dict], thr: float) -> list[tuple[dict, dict, float]]:
    """Pairs of cuboids whose footprints overlap (intersection / smaller footprint >= thr) and whose heights meet."""
    out = []
    polys = [_footprint(b) for b in boxes]
    rad = [math.hypot(*b['size'][:2]) / 2 for b in boxes]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if math.hypot(a['center'][0] - b['center'][0], a['center'][1] - b['center'][1]) > rad[i] + rad[j]:
                continue
            if a['center'][2] + a['size'][2] < b['center'][2] or b['center'][2] + b['size'][2] < a['center'][2]:
                continue
            inter = polys[i].intersection(polys[j]).area
            frac = inter / max(min(polys[i].area, polys[j].area), 1e-6)
            if frac >= thr:
                out.append((a, b, round(float(frac), 2)))
    return out


def size_outliers(box: dict, cfg: dict) -> list[str]:
    """Which of l, w, h are outside the class range (widened by size_margin)."""
    b = cfg['size'].get(box['cls'])
    if not b:
        return []
    l, w, h = box['size']
    k = cfg['size_margin']
    vals = {'l': l, 'w': w, 'h': h}
    return [n for n, v in vals.items() if n in b and not b[n][0] / k <= v <= b[n][1] * k]


def _yaw_gap_deg(a: float, b: float) -> float:
    """Angle between two axes, ignoring direction (0-90°)."""
    d = abs(_wrap(a - b)) % math.pi
    return math.degrees(min(d, math.pi - d))


def judge(box: dict, ev: dict, cfg: dict) -> tuple[list[dict], bool]:
    """LiDAR flags for one cuboid and whether the ray / point evidence was enough to verify it."""
    g = group(box['cls'])
    flags = []
    rays = ev.get('rays') or {}
    support = rays.get('hit', 0) + rays.get('pass', 0)
    pass_frac = rays.get('pass', 0) / support if support else 0.0
    checked = support >= cfg['min_support']
    if support >= cfg['empty_min_support'] and rays['hit'] <= cfg['empty_max_hits'] \
            and ev['n_body'] <= cfg['empty_max_hits'] + 1:
        flags.append({'type': 'LIDAR_EMPTY', 'detail': {'support': support, 'hit': rays['hit'], 'pass': rays['pass'],
                                                         'occ': rays['occ']},
                      'msg': f"{rays['pass']} tia LiDAR xuyên thẳng qua cuboid, chỉ {rays['hit']} tia chạm vật – cuboid "
                             f"rỗng (thừa hoặc đặt sai chỗ)."})
    elif support >= cfg['free'][g][0] and pass_frac > cfg['free'][g][1]:
        flags.append({'type': 'LIDAR_FREE', 'detail': {'support': support, 'hit': rays['hit'], 'pass': rays['pass'],
                                                        'pass_frac': round(pass_frac, 2), 'occ': rays['occ']},
                      'msg': f"{pass_frac:.0%} số tia tới được cuboid đi xuyên qua mà không chạm gì ({rays['pass']}/{support}) "
                             f"– cuboid lấn ra khoảng trống: quá to hoặc lệch chỗ."})
    n_in, n_sp = ev['n_inside'], ev['n_spill']
    if n_sp >= cfg['spill'][g][0] and n_sp / (n_in + n_sp) > cfg['spill'][g][1]:
        flags.append({'type': 'LIDAR_SPILL', 'detail': {'inside': n_in, 'spill': n_sp, 'out_m': ev['spill_out_m']},
                      'msg': f"{n_sp} điểm của vật nằm ngoài cuboid (thò ra tới {ev['spill_out_m']:.1f} m), trong cuboid "
                             f"{n_in} điểm – cuboid quá nhỏ hoặc lệch khỏi vật."})
    ax = ev.get('axis')
    if ax and ax['n'] >= cfg['heading'][g][0] and ax['long'] >= 0.6 * CLASS_SIZES[box['cls']][0] \
            and ax['long'] >= 1.5 * ax['short']:
        gap = _yaw_gap_deg(ax['yaw'], box['yaw'])
        if gap > cfg['heading'][g][1]:
            flags.append({'type': 'LIDAR_HEADING', 'detail': {'gap_deg': round(gap, 1), 'points_yaw': round(math.degrees(ax['yaw']), 1),
                                                               'long_m': ax['long']},
                          'msg': f"Đám điểm của vật kéo dài {ax['long']:.1f} m theo hướng lệch {gap:.0f}° so với chiều dài "
                                 f"cuboid – cuboid xoay sai."})
    bad = size_outliers(box, cfg)
    if bad:
        names = {'l': 'dài', 'w': 'rộng', 'h': 'cao'}
        b, k = cfg['size'][box['cls']], cfg['size_margin']
        parts = [f"{names[n]} {box['size']['lwh'.index(n)]:.2f} m (thường {b[n][0] / k:.1f}–{b[n][1] * k:.1f})" for n in bad]
        flags.append({'type': 'SIZE_IMPLAUSIBLE', 'detail': {'dims': bad},
                      'msg': f"Kích thước bất thường với {box['cls']}: " + ', '.join(parts) + '.'})
    gap = ev.get('ground_gap')
    lo, hi = cfg['ground'][g]
    if gap is not None and gap > hi:
        flags.append({'type': 'FLOATING', 'detail': {'gap_m': gap},
                      'msg': f"Đáy cuboid cao hơn mặt đất xung quanh {gap:.2f} m – cuboid lơ lửng."})
    elif gap is not None and gap < lo:
        flags.append({'type': 'SUNKEN', 'detail': {'gap_m': gap},
                      'msg': f"Đáy cuboid thấp hơn mặt đất xung quanh {-gap:.2f} m – cuboid chìm xuống đất."})
    return flags, checked or bool(flags)


def lidar_check(boxes: list[dict], sweep: Sweep, cfg: dict) -> tuple[list[dict], dict]:
    """(flags, evidence per box_id). Flags carry type, box_id, detail, msg; the caller adds sample / camera."""
    flags, info = [], {}
    for b in boxes:
        ev = box_evidence(b, sweep)
        fl, checked = judge(b, ev, cfg)
        rays = ev.get('rays') or {}
        info[b['box_id']] = {'checked': checked, 'rays': {k: v for k, v in rays.items() if k != 'pass_xy'},
                             'pass_xy': rays.get('pass_xy', []), 'n_inside': ev['n_inside'], 'n_spill': ev['n_spill'],
                             'ground_gap': ev['ground_gap']}
        flags += [{**f, 'box_id': b['box_id'], 'cls_3d': b['cls']} for f in fl]
    # overlap: blame the cuboid with less LiDAR support (the other one probably sits on the object)
    for a, b, frac in overlaps(boxes, cfg['overlap']):
        ha, hb = info[a['box_id']]['rays'].get('hit', 0), info[b['box_id']]['rays'].get('hit', 0)
        worse, other = (a, b) if ha <= hb else (b, a)
        flags.append({'type': 'BEV_OVERLAP', 'box_id': worse['box_id'], 'cls_3d': worse['cls'], 'other_id': other['box_id'],
                      'detail': {'overlap': frac, 'other_id': other['box_id'], 'other_cls': other['cls']},
                      'msg': f"Chồng lên cuboid {other['cls']} {other['box_id'][-6:]} ({frac:.0%} diện tích đáy) – hai vật "
                             f"không thể chiếm cùng một chỗ: gán trùng hoặc dời nhầm."})
    return flags, info
