"""2D → 3D: propose a cuboid for a camera detection from the LiDAR points inside its frustum.

  drop ground (local min-z grid) → non-ground points inside the shrunk 2D box (depth > 1 m) →
  connected components in 3D → for the biggest clusters: grow to the whole object, yaw by minimum-area
  rectangle (both length-axis choices), size = observed extent grown to the class prior on the side
  hidden from the sensor, bottom on the local ground
  → keep the candidate whose projection best overlaps the 2D box, minus a penalty for sizes far from the
  class prior. Only when no cluster is found: class prior behind the point where the ray through the
  bottom-center of the 2D box meets the ground (seen end-on or side-on).

Tuned on nuScenes-mini train with labeler/eval_propose.py; see README for the val numbers.
"""
import numpy as np
from scipy.ndimage import minimum_filter
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from m44.geometry import box_corners, iou, project_box

CLASS_SIZES = {  # typical nuScenes l, w, h (m); keep in sync with frontend/src/geometry.js
    'car': (4.6, 1.9, 1.7), 'truck': (7.0, 2.5, 3.0), 'bus': (11.0, 2.9, 3.5), 'trailer': (10.0, 2.6, 3.8),
    'construction_vehicle': (6.5, 2.8, 3.2), 'pedestrian': (0.7, 0.7, 1.75), 'motorcycle': (2.1, 0.8, 1.5),
    'bicycle': (1.7, 0.6, 1.3), 'traffic_cone': (0.4, 0.4, 1.0), 'barrier': (0.5, 2.5, 1.0),
}
# COCO class of a detection -> class of the proposed cuboid
FROM_COCO = {'person': 'pedestrian', 'car': 'car', 'truck': 'truck', 'bus': 'bus', 'bicycle': 'bicycle',
             'motorcycle': 'motorcycle'}

LIDAR_HEIGHT = 1.84   # nuScenes LIDAR_TOP above the ground
GROUND_CELL = 1.0     # m, grid for the local ground height
GROUND_RANGE = 80.0   # m, half size of the ground grid
GROUND_MARGIN = 0.25  # points lower than ground + this are ground
SHRINK = 0.1          # share of the 2D box width/height cut on each side (background bleeding in)
SHRINK_NARROW = 0.05  # same for narrow boxes (width < 0.8 height: people, bikes), which have few points
MIN_POINTS = 3
TOP_CLUSTERS = 4      # frustum clusters tried (a wall behind the object is often the biggest)
SIZE_PENALTY = 0.3    # per unit of |log(l / prior)| + |log(w / prior)|: keeps the fit from picking a wall
SMALL = {'pedestrian', 'bicycle', 'motorcycle', 'traffic_cone'}
MIN_BATCH_FIT = 0.1   # 2D IoU a batch proposal must reach with its own detection


class Ground:
    """z of the ground near (x, y): lowest point in the 3x3 neighbourhood of 1 m cells."""

    def __init__(self, pts: np.ndarray):
        n = int(2 * GROUND_RANGE / GROUND_CELL)
        grid = np.full((n, n), np.inf)
        ij = self._cells(pts[:, 0], pts[:, 1])
        ok = (ij >= 0).all(axis=1) & (ij < n).all(axis=1)
        np.minimum.at(grid, (ij[ok, 0], ij[ok, 1]), pts[ok, 2])
        grid = minimum_filter(grid, size=3, mode='constant', cval=np.inf)
        self.known = np.isfinite(grid)  # cells with LiDAR returns nearby; the rest fall back to the mount height
        self.grid = np.where(self.known, grid, -LIDAR_HEIGHT)
        self.n = n

    def is_known(self, x, y) -> np.ndarray:
        ij = self._cells(np.asarray(x), np.asarray(y))
        inside = ((ij >= 0) & (ij < self.n)).all(axis=-1)
        ij = np.clip(ij, 0, self.n - 1)
        return inside & self.known[ij[..., 0], ij[..., 1]]

    @staticmethod
    def _cells(x, y) -> np.ndarray:
        return np.floor((np.stack([x, y], axis=-1) + GROUND_RANGE) / GROUND_CELL).astype(np.int64)

    def __call__(self, x, y):
        ij = np.clip(self._cells(np.asarray(x), np.asarray(y)), 0, self.n - 1)
        z = self.grid[ij[..., 0], ij[..., 1]]
        return float(z) if np.ndim(z) == 0 else z


def _frustum(pts: np.ndarray, cam: dict, bbox) -> np.ndarray:
    M, K = np.asarray(cam['lidar2cam']), np.asarray(cam['cam2img'])
    pc = pts[:, :3] @ M[:3, :3].T + M[:3, 3]
    front = pc[:, 2] > 1.0
    uvw = pc[front] @ K.T
    uv = uvw[:, :2] / uvw[:, 2:3]
    x1, y1, x2, y2 = bbox
    shrink = SHRINK_NARROW if x2 - x1 < 0.8 * (y2 - y1) else SHRINK
    dx, dy = (x2 - x1) * shrink, (y2 - y1) * shrink
    inside = (uv[:, 0] > x1 + dx) & (uv[:, 0] < x2 - dx) & (uv[:, 1] > y1 + dy) & (uv[:, 1] < y2 - dy)
    return pts[front][inside]


def _min_area_yaw(xy: np.ndarray) -> float:
    best, best_yaw = np.inf, 0.0
    for yaw in np.deg2rad(np.arange(0, 90, 1.0)):
        c, s = np.cos(yaw), np.sin(yaw)
        a, b = xy @ [c, s], xy @ [-s, c]
        area = np.ptp(a) * np.ptp(b)
        if area < best:
            best, best_yaw = area, yaw
    return best_yaw


def _grow(lo: float, hi: float, size: float, sensor: float) -> tuple[float, float]:
    """Extend [lo, hi] to `size`, keeping the face that the sensor sees."""
    if hi - lo >= size:
        return lo, hi
    return (lo, lo + size) if abs(sensor - lo) < abs(sensor - hi) else (hi - size, hi)


def _clusters(pts: np.ndarray, eps: float) -> np.ndarray:
    n = len(pts)
    pairs = cKDTree(pts[:, :3]).query_pairs(eps, output_type='ndarray')
    if len(pairs):
        graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    else:
        graph = coo_matrix((n, n))
    return connected_components(graph, directed=False)[1]


def _grow_cluster(seed: np.ndarray, nonground: np.ndarray, cls: str) -> np.ndarray:
    """The whole object around a frustum cluster: connected non-ground points near it (the 2D box crop
    cuts objects at the image border and SHRINK cuts their sides)."""
    l0 = CLASS_SIZES[cls][0]
    mid = seed[:, :2].mean(axis=0)
    near = nonground[np.hypot(*(nonground[:, :2] - mid).T) < l0 * 0.75 + 1.0]
    pts = np.vstack([seed, near])
    labels = _clusters(pts, 0.3 if cls in SMALL else 0.5)
    obj = pts[np.isin(labels, np.unique(labels[:len(seed)]))]
    obj = np.unique(obj, axis=0)  # seed points are also in `near`
    extent = np.ptp(obj[:, :2], axis=0).max()
    return obj if extent < 1.5 * l0 + 0.5 else seed  # merged with neighbours: keep the seed only


def _fit(obj: np.ndarray, cls: str, ground: Ground) -> list[dict]:
    """Box candidates for one point cluster (two length-axis choices for vehicles)."""
    l0, w0, h0 = CLASS_SIZES[cls]
    xy = obj[:, :2]
    top = float(obj[:, 2].max())
    n = int(len(obj))

    def finish(cx, cy, l, w, yaw):
        gz = ground(cx, cy)
        h = top - gz if top - gz > 0.6 * h0 else h0  # partly seen tops (low beams) fall back to the prior
        return {'center': [float(cx), float(cy), float(gz)], 'size': [float(l), float(w), float(h)],
                'yaw': float((yaw + np.pi) % (2 * np.pi) - np.pi), 'method': 'lidar_cluster', 'n_points': n}

    if cls in SMALL:
        # too few points for a heading: prior footprint, center pushed half a width away from the sensor
        mid = np.median(xy, axis=0)
        ray = mid / max(np.linalg.norm(mid), 1e-6)
        cx, cy = mid + ray * w0 / 4
        return [finish(cx, cy, l0, w0, np.arctan2(ray[1], ray[0]))]

    out = []
    base = _min_area_yaw(xy)
    for yaw in (base, base + np.pi / 2):  # which rectangle side is the length is decided by the 2D fit
        c, s = np.cos(yaw), np.sin(yaw)
        a, b = xy @ [c, s], xy @ [-s, c]
        # grow each axis to the prior on the side hidden from the sensor (at the origin)
        a_lo, a_hi = _grow(a.min(), a.max(), l0, 0.0)
        b_lo, b_hi = _grow(b.min(), b.max(), w0, 0.0)
        am, bm = (a_lo + a_hi) / 2, (b_lo + b_hi) / 2
        cx, cy = c * am - s * bm, s * am + c * bm
        if np.cos(yaw) < 0:  # 180° ambiguity: most traffic runs along the ego heading
            yaw += np.pi
        out.append(finish(cx, cy, a_hi - a_lo, b_hi - b_lo, yaw))
    return out


def _ground_ray(cam: dict, bbox, ground: Ground):
    """Point where the ray through the bottom-center of the 2D box meets the ground, and the ray direction."""
    M, K = np.asarray(cam['lidar2cam']), np.asarray(cam['cam2img'])
    ray_cam = np.linalg.solve(K, [(bbox[0] + bbox[2]) / 2, bbox[3], 1.0])
    R, t = M[:3, :3], M[:3, 3]
    origin, ray = -R.T @ t, R.T @ ray_cam  # camera center and ray in the LiDAR frame
    if ray[2] >= -1e-6:
        return None, None
    gz = -LIDAR_HEIGHT
    for _ in range(2):  # refine with the local ground once
        p = origin + (gz - origin[2]) / ray[2] * ray
        gz = ground(p[0], p[1])
    return np.array([p[0], p[1], gz]), ray[:2] / np.linalg.norm(ray[:2])


def _fallback(cls: str, cam: dict, bbox, ground: Ground) -> list[dict]:
    """Prior-sized boxes behind the ground hit of the 2D box, seen end-on or side-on."""
    p, ray = _ground_ray(cam, bbox, ground)
    if p is None:
        return []
    l, w, h = CLASS_SIZES[cls]
    out = []
    for side_on in (False, True):
        depth = (w if side_on else l) / 2  # the ray hits the visible face; the center is half an extent behind
        yaw = float(np.arctan2(ray[1], ray[0]) + (np.pi / 2 if side_on else 0.0))
        out.append({'center': [float(p[0] + ray[0] * depth), float(p[1] + ray[1] * depth), float(p[2])],
                    'size': [l, w, h], 'yaw': yaw, 'method': 'ground_ray', 'n_points': 0})
    return out


class Sweep:
    """Ground model and non-ground points of one LiDAR sweep, reused for every proposal on that frame."""

    def __init__(self, points: np.ndarray):
        """points: N x 4 (x, y, z, intensity) or N x 5 with the nuScenes ring index (needed by the LiDAR QC
        ray casting, labeler/lidar_qc.py)."""
        self.raw = points
        points = points[:, :4]
        self.points = points
        self.ground = Ground(points)
        self.nonground = points[points[:, 2] > self.ground(points[:, 0], points[:, 1]) + GROUND_MARGIN]
        self.qc_cache: dict = {}  # labeler/lidar_qc.py: range image and per-cuboid stats of this sweep


def propose(sweep: Sweep, cam: dict, bbox, coco_cls: str) -> dict | None:
    """Cuboid (LiDAR frame, bottom-center, size l w h) for a 2D detection, or None.

    Candidates from the biggest frustum clusters are projected back into the camera and scored by overlap
    with the 2D box; the ground-ray fallback is used only without any cluster (it fits the 2D box by
    construction but its depth is a guess).
    """
    cls = FROM_COCO.get(coco_cls, coco_cls if coco_cls in CLASS_SIZES else 'car')
    fr = _frustum(sweep.nonground, cam, bbox)

    cands = []
    if len(fr) >= MIN_POINTS:
        labels = _clusters(fr, 0.4 if cls in SMALL else 0.7)
        counts = np.bincount(labels)
        for k in np.argsort(-counts)[:TOP_CLUSTERS]:
            if counts[k] < MIN_POINTS:
                break
            cands += _fit(_grow_cluster(fr[labels == k], sweep.nonground, cls), cls, sweep.ground)
    if not cands:
        cands = _fallback(cls, cam, bbox, sweep.ground)

    l0, w0, _ = CLASS_SIZES[cls]
    best, best_score, best_iou = None, -np.inf, 0.0
    for c in cands:
        p = project_box(c, cam)
        fit = iou(p['bbox'], bbox) if p else 0.0
        score = fit - SIZE_PENALTY * (abs(np.log(c['size'][0] / l0)) + abs(np.log(c['size'][1] / w0)))
        if score > best_score:
            best, best_score, best_iou = c, score, fit
    return None if best is None else {**best, 'cls': cls, 'fit_iou': round(float(best_iou), 3)}


def box_overlaps(a: dict, others: list[dict], min_dist: float = 1.0) -> bool:
    """Same object already boxed: centers closer than min_dist or the footprint center inside another box."""
    for b in others:
        if np.hypot(a['center'][0] - b['center'][0], a['center'][1] - b['center'][1]) < min_dist:
            return True
        c = box_corners(b['center'], b['size'], b['yaw'])[:4, :2]
        rel = np.subtract(a['center'][:2], b['center'][:2])
        ex, ey = (c[0] - c[3]) / 2, (c[0] - c[1]) / 2  # half length / half width vectors
        if abs(rel @ ex) <= ex @ ex and abs(rel @ ey) <= ey @ ey:
            return True
    return False


def propose_missing(sweep: Sweep, cams: dict, flags: list[dict], boxes: list[dict]) -> list[dict]:
    """Proposals for the MISSING_3D flags, one per object across cameras (biggest 2D box first).

    A proposal whose projection misses its own 2D box is a guess, not worth the annotator's time, and one
    on an object that already has a cuboid (or an earlier proposal) is a duplicate: both are skipped.
    Each result carries the camera it came from in `cam`.
    """
    missing = sorted((f for f in flags if f['type'] == 'MISSING_3D'),
                     key=lambda f: -(f['det_bbox'][3] - f['det_bbox'][1]))
    new = []
    for f in missing:
        p = propose(sweep, cams[f['cam']], f['det_bbox'], f['cls_2d'])
        if p is not None and p['fit_iou'] >= MIN_BATCH_FIT and not box_overlaps(p, boxes + new):
            new.append({**p, 'cam': f['cam']})
    return new
