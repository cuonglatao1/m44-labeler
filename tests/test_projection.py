"""Our projection must agree with the 2D boxes mmdet3d precomputed in the info pkl (cam_instances)."""
import os
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from m44.geometry import _to_cam, iou, project_box  # noqa: E402
from m44.loader import load_frames  # noqa: E402

DEMO = os.environ.get('M44_DEMO_DIR', '/root/work/mmdetection3d/demo/data/nuscenes')
PKL = f'{DEMO}/n015-2018-07-24-11-22-45+0800.pkl'


def test_projection_matches_mmdet3d():
    frame = load_frames(PKL, DEMO)[0]
    raw = pickle.load(open(PKL, 'rb'))['data_list'][0]
    ious = []
    for cam_name, cam in frame['cams'].items():
        for ref in raw['cam_instances'][cam_name]:
            ref_center = np.asarray(ref['bbox_3d'][:3])  # camera frame, gravity center

            def gravity_in_cam(b):
                g = np.asarray(b['center']) + [0, 0, b['size'][2] / 2]
                return _to_cam(g[None], cam['lidar2cam'])[0]

            # find our box with the same physical center
            best = min(frame['boxes'], key=lambda b: np.linalg.norm(gravity_in_cam(b) - ref_center))
            dist = np.linalg.norm(gravity_in_cam(best) - ref_center)
            if dist > 0.2:
                continue
            p = project_box(best, cam)
            if p is not None:
                ious.append(iou(p['bbox'], ref['bbox']))
    ious = np.array(ious)
    print(f'compared {len(ious)} boxes, median IoU {np.median(ious):.3f}, '
          f'>=0.9: {np.mean(ious >= 0.9):.1%}, min {ious.min():.3f}')
    # ~1 px residual: mmdet3d's reference boxes compensate ego motion between the LiDAR and
    # camera timestamps (~30 ms), our static lidar2cam does not. Small far boxes amplify it in IoU.
    assert len(ious) > 50
    assert np.median(ious) > 0.9


if __name__ == '__main__':
    test_projection_matches_mmdet3d()
