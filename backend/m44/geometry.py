"""Cuboid geometry and LiDAR → camera projection."""
import numpy as np

IMG_WH = (1600, 900)  # nuScenes camera resolution

# corner order: bottom 0-3, top 4-7
EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]


def box_corners(center, size, yaw) -> np.ndarray:
    """8 corners (8x3) of a LiDAR-frame box whose `center` is the bottom-center."""
    l, w, h = size
    x = np.array([1, 1, -1, -1, 1, 1, -1, -1]) * l / 2
    y = np.array([1, -1, -1, 1, 1, -1, -1, 1]) * w / 2
    z = np.array([0, 0, 0, 0, 1, 1, 1, 1]) * h
    c, s = np.cos(yaw), np.sin(yaw)
    return np.stack([c * x - s * y, s * x + c * y, z], axis=1) + np.asarray(center)


def _to_cam(pts: np.ndarray, lidar2cam) -> np.ndarray:
    return (np.c_[pts, np.ones(len(pts))] @ np.asarray(lidar2cam).T)[:, :3]


def _to_img(pc: np.ndarray, cam2img) -> np.ndarray:
    uv = pc @ np.asarray(cam2img).T
    return uv[:, :2] / uv[:, 2:3]


def project_box(box: dict, cam: dict, img_wh=IMG_WH, near: float = 0.1) -> dict | None:
    """Project a box into one camera. Returns the clipped 2D bbox or None if not visible.

    Edges crossing the camera plane are clipped at `near` so boxes partly behind
    the camera still get a correct 2D extent.
    """
    pc = _to_cam(box_corners(box['center'], box['size'], box['yaw']), cam['lidar2cam'])
    front = pc[:, 2] > near
    if not front.any():
        return None

    pts = [pc[i] for i in range(8) if front[i]]
    for a, b in EDGES:
        if front[a] != front[b]:
            t = (near - pc[a, 2]) / (pc[b, 2] - pc[a, 2])
            pts.append(pc[a] + t * (pc[b] - pc[a]))
    uv = _to_img(np.array(pts), cam['cam2img'])
    x1, y1 = uv.min(axis=0)
    x2, y2 = uv.max(axis=0)

    w_img, h_img = img_wh
    cx1, cy1, cx2, cy2 = max(x1, 0), max(y1, 0), min(x2, w_img), min(y2, h_img)
    if cx2 - cx1 < 1 or cy2 - cy1 < 1:
        return None

    gravity = np.asarray(box['center']) + [0, 0, box['size'][2] / 2]
    corners_2d = _to_img(pc, cam['cam2img'])
    return {
        'bbox': [float(cx1), float(cy1), float(cx2), float(cy2)],
        'depth': float(_to_cam(gravity[None], cam['lidar2cam'])[0, 2]),
        'visible_frac': float((cx2 - cx1) * (cy2 - cy1) / max((x2 - x1) * (y2 - y1), 1e-6)),
        # corners behind the camera are None so the drawer can skip those edges
        'corners_2d': [uv_i.tolist() if f else None for uv_i, f in zip(corners_2d, front)],
    }


def project_frame(frame: dict) -> list[dict]:
    out = []
    for cam_name, cam in frame['cams'].items():
        for box in frame['boxes']:
            p = project_box(box, cam)
            if p is not None:
                out.append({'sample': frame['sample'], 'cam': cam_name, 'box_id': box['box_id'],
                            'cls': box['cls'], 'visibility': box.get('visibility'),
                            'night': frame.get('night'), **p})
    return out


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def overlap_frac(a, b) -> float:
    """Fraction of box `a` covered by box `b`."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = (a[2] - a[0]) * (a[3] - a[1])
    return ix * iy / area if area > 0 else 0.0
