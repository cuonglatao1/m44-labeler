"""The devkit loader must reproduce the mmdet3d-info loader frame by frame (needs nuScenes-mini + its infos)."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from m44.loader import load_frames, load_frames_nusc  # noqa: E402

ROOT = os.environ.get('NUSC_ROOT', 'data/nuscenes')


def test_devkit_loader_matches_infos(split='val'):
    info = Path(ROOT) / f'nuscenes_infos_{split}.pkl'
    if not info.exists():
        print(f'skip: {info} not found (only generated with mmdet3d)')
        return
    a, b = load_frames_nusc(ROOT, split), load_frames(str(info), ROOT)
    assert [f['sample'] for f in a] == [f['sample'] for f in b]
    worst = {'center': 0.0, 'size': 0.0, 'yaw': 0.0, 'lidar2cam': 0.0, 'cam2img': 0.0}
    for fa, fb in zip(a, b):
        assert [x['box_id'] for x in fa['boxes']] == [x['box_id'] for x in fb['boxes']]
        for x, y in zip(fa['boxes'], fb['boxes']):
            assert x['cls'] == y['cls'] and x['visibility'] == y['visibility']
            worst['center'] = max(worst['center'], np.abs(np.subtract(x['center'], y['center'])).max())
            worst['size'] = max(worst['size'], np.abs(np.subtract(x['size'], y['size'])).max())
            d = (x['yaw'] - y['yaw'] + np.pi) % (2 * np.pi) - np.pi
            worst['yaw'] = max(worst['yaw'], abs(d))
        for cam in fa['cams']:
            for k in ('lidar2cam', 'cam2img'):
                worst[k] = max(worst[k], np.abs(np.subtract(fa['cams'][cam][k], fb['cams'][cam][k])).max())
            assert Path(fa['cams'][cam]['img_path']).name == Path(fb['cams'][cam]['img_path']).name
    print(f'{len(a)} frames, {sum(len(f["boxes"]) for f in a)} boxes, max abs diff: '
          + ', '.join(f'{k}={v:.2e}' for k, v in worst.items()))
    assert max(worst.values()) < 1e-3


if __name__ == '__main__':
    test_devkit_loader_matches_infos()
