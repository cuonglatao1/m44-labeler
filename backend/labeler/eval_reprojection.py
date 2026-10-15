"""Reprojection error of the camera check (an M44 metric): on clean nuScenes GT, how far does each projected cuboid
land from the YOLO box it is matched to? Pixels (center distance), normalised by the box size, and IoU; overall, by
distance and by class. Tuned cfg (configs/tuned.json), as in the app.

  python -m labeler.eval_reprojection --split val
"""
import argparse
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from m44.evaluate import reprojection_stats
from m44.geometry import project_frame
from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, check, load_cfg

ROOT = Path(__file__).resolve().parents[2]
BINS = [(0, 20), (20, 35), (35, 50)]


def rel_err(m: dict) -> float:
    """Center distance / diagonal of the projected box: comparable across near and far objects."""
    p, d = m['p_bbox'], m['d_bbox']
    c = np.hypot((p[0] + p[2] - d[0] - d[2]) / 2, (p[1] + p[3] - d[1] - d[3]) / 2)
    return float(c / max(np.hypot(p[2] - p[0], p[3] - p[1]), 1e-6))


def row(name: str, ms: list[dict]) -> str:
    s = reprojection_stats(ms)
    if not s:
        return f'{name:<20}{0:>6}'
    rel = np.median([rel_err(m) for m in ms]) * 100
    return (f"{name:<20}{s['pairs']:>6}{s['center_err_px_median']:>10.1f}{s['center_err_px_p90']:>9.1f}"
            f"{rel:>9.1f}%{s['iou_median']:>9.3f}{s['iou_mean']:>9.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    args = ap.parse_args()

    import json
    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    det_dir = ROOT / 'cache' / 'dets'
    frames = load_frames_nusc(args.nusc_root, args.split)

    allm, by_cls, by_dist = [], defaultdict(list), defaultdict(list)
    n_flags = 0
    for f in frames:
        p = det_dir / f"{f['sample']}.json"
        dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        proj = project_frame(f)
        depth = {(q['box_id'], q['cam']): q['depth'] for q in proj}
        cls = {b['box_id']: b['cls'] for b in f['boxes']}
        flags, matches = check(proj, dets, cfg)
        n_flags += len(flags)
        for m in matches:
            allm.append(m)
            by_cls[cls[m['box_id']]].append(m)
            z = depth[(m['box_id'], m['cam'])]
            for lo, hi in BINS:
                if lo <= z < hi:
                    by_dist[f'{lo}–{hi} m'].append(m)

    print(f'{len(frames)} frames ({args.split}), clean GT; cuboid ↔ YOLO pairs the camera check matched')
    print(f"camera flags on clean GT: {n_flags} ({n_flags / len(frames):.2f} / frame)\n")
    print(f"{'':<20}{'pairs':>6}{'px med':>10}{'px p90':>9}{'rel med':>10}{'IoU med':>9}{'IoU mean':>9}")
    print(row('all', allm))
    for lo, hi in BINS:
        print(row(f'{lo}–{hi} m', by_dist[f'{lo}–{hi} m']))
    for c in sorted(by_cls, key=lambda c: -len(by_cls[c])):
        print(row(c, by_cls[c]))


if __name__ == '__main__':
    main()
