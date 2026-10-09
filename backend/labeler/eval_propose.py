"""How close are the 2D → 3D proposals to the nuScenes GT?

For every GT cuboid the M44 check matched to a YOLO box (clean GT, tuned cfg), propose a cuboid from that YOLO
box alone and compare it with the GT cuboid: BEV IoU, center error, heading error (mod 180°), size error.

  python -m labeler.eval_propose --split val
"""
import argparse
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

from m44.geometry import box_corners, project_frame
from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, check, load_cfg

from .dataset import Dataset
from .propose import Sweep, propose

ROOT = Path(__file__).resolve().parents[2]


def bev_iou(a: dict, b: dict) -> float:
    pa, pb = (Polygon(box_corners(x['center'], x['size'], x['yaw'])[:4, :2]) for x in (a, b))
    inter = pa.intersection(pb).area
    return inter / (pa.area + pb.area - inter)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--max-frames', type=int)
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    det_dir = ROOT / 'cache' / 'dets'
    frames = load_frames_nusc(args.nusc_root, args.split)[:args.max_frames]
    ds = Dataset.__new__(Dataset)  # only need dets(); avoid loading both splits again
    ds.det_dir = det_dir

    rows = defaultdict(list)
    for f in frames:
        sweep = Sweep(np.fromfile(f["lidar_path"], dtype=np.float32).reshape(-1, 5)[:, :4])
        _, matches = check(project_frame(f), ds.dets(f['sample']), cfg)
        gt = {b['box_id']: b for b in f['boxes']}
        dets = {(d['cam'], tuple(d['bbox'])): d for d in ds.dets(f['sample'])}
        seen = set()
        for m in matches:
            if m['box_id'] in seen:  # one proposal per object (first camera that saw it)
                continue
            seen.add(m['box_id'])
            d = dets[(m['cam'], tuple(m['d_bbox']))]
            p = propose(sweep, f['cams'][m['cam']], d['bbox'], d['cls'])
            g = gt[m['box_id']]
            if p is None:
                rows[g['cls']].append(None)
                continue
            dyaw = abs((p['yaw'] - g['yaw'] + np.pi / 2) % np.pi - np.pi / 2)
            rows[g['cls']].append({
                'iou': bev_iou(p, g), 'center': float(np.hypot(*np.subtract(p['center'][:2], g['center'][:2]))),
                'yaw': np.rad2deg(dyaw), 'size': float(np.abs(np.subtract(p['size'], g['size'])).mean()),
                'method': p['method'],
            })

    print(f'{len(frames)} frames ({args.split}); proposals from the YOLO box matched to each GT cuboid\n')
    print(f"{'class':<22}{'n':>5}{'none':>6}{'IoU med':>9}{'IoU>=.5':>9}{'ctr med m':>11}{'yaw med°':>10}"
          f"{'size med m':>12}{'fallback':>10}")
    for cls, rs in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        ok = [r for r in rs if r]
        if not ok:
            continue
        iou = np.array([r['iou'] for r in ok])
        print(f"{cls:<22}{len(rs):>5}{len(rs) - len(ok):>6}{np.median(iou):>9.2f}{np.mean(iou >= 0.5):>9.0%}"
              f"{np.median([r['center'] for r in ok]):>11.2f}{np.median([r['yaw'] for r in ok]):>10.1f}"
              f"{np.median([r['size'] for r in ok]):>12.2f}"
              f"{np.mean([r['method'] == 'ground_ray' for r in ok]):>10.0%}")


if __name__ == '__main__':
    main()
