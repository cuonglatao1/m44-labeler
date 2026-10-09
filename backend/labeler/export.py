"""Export saved cuboids: raw (our LiDAR-frame boxes) or nuScenes detection-results JSON (global frame)."""
import numpy as np
from pyquaternion import Quaternion


def to_nuscenes(frame: dict, boxes: list[dict]) -> list[dict]:
    """Boxes in the nuScenes results format (gravity center, wlh, global rotation) with score 1."""
    T = np.asarray(frame['lidar2global'])
    out = []
    for b in boxes:
        l, w, h = b['size']
        center = T @ [b['center'][0], b['center'][1], b['center'][2] + h / 2, 1.0]
        # nuScenes boxes are yaw-only in the global frame: rotate the heading, drop the sensor tilt
        heading = T[:3, :3] @ [np.cos(b['yaw']), np.sin(b['yaw']), 0.0]
        rot = Quaternion(axis=[0, 0, 1], angle=float(np.arctan2(heading[1], heading[0])))
        out.append({
            'sample_token': frame['sample'], 'translation': center[:3].tolist(), 'size': [w, l, h],
            'rotation': rot.elements.tolist(), 'velocity': [0.0, 0.0],
            'detection_name': b['cls'], 'detection_score': 1.0, 'attribute_name': '',
        })
    return out
