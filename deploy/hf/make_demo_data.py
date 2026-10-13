"""Copy the files the public demo needs into one folder: nuScenes-mini metadata and map masks + the keyframes of the mini val
scenes (LiDAR + 6 cameras) and their cached YOLO detections.

    .venv\Scripts\python.exe deploy/hf/make_demo_data.py --nusc-root D:/data/nuscenes --out D:/m44-demo-data
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from m44.loader import load_frames_nusc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nusc-root', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    src, out = Path(args.nusc_root), Path(args.out)
    nusc_out = out / 'nuscenes'
    for d in ('v1.0-mini', 'maps'):  # the devkit refuses to load without the map masks
        shutil.copytree(src / d, nusc_out / d, dirs_exist_ok=True)

    frames = load_frames_nusc(str(src), 'val')
    n_bytes = 0
    for f in frames:
        for p in [f['lidar_path']] + [c['img_path'] for c in f['cams'].values()]:
            p = Path(p)
            dst = nusc_out / p.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            n_bytes += p.stat().st_size
        det = ROOT / 'cache' / 'dets' / f"{f['sample']}.json"
        if det.exists():
            (out / 'dets').mkdir(parents=True, exist_ok=True)
            shutil.copy2(det, out / 'dets' / det.name)
    print(f'{len(frames)} frames, {n_bytes / 2**20:.0f} MB of sensor files -> {out}')


if __name__ == '__main__':
    main()
