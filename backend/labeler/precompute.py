"""Fill the YOLO detection cache (one JSON per sample in cache/dets/).

  python -m labeler.precompute --import-json D:/m44-consistency-checker/out/mini_val/det_2d.json
  python -m labeler.precompute --split val            # run YOLO (needs requirements-detect.txt)
"""
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DET_DIR = ROOT / 'cache' / 'dets'


def write(dets: list[dict], overwrite: bool) -> int:
    by_sample = defaultdict(list)
    for d in dets:
        by_sample[d['sample']].append(d)
    DET_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for sample, ds in by_sample.items():
        p = DET_DIR / f'{sample}.json'
        if p.exists() and not overwrite:
            continue
        p.write_text(json.dumps(ds), encoding='utf-8')
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--import-json', nargs='*', default=[], help='det_2d.json files from M44 runs')
    ap.add_argument('--split', choices=['train', 'val', 'all'], help='run YOLO on this split')
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--version', default='v1.0-mini')
    ap.add_argument('--weights', default=str(ROOT / 'weights' / 'yolo11m.pt'))
    ap.add_argument('--overwrite', action='store_true')
    args = ap.parse_args()

    for path in args.import_json:
        n = write(json.loads(Path(path).read_text(encoding='utf-8')), args.overwrite)
        print(f'{path}: {n} samples written')

    if args.split:
        from m44.detect import detect
        from m44.loader import load_frames_nusc

        frames = load_frames_nusc(args.nusc_root, args.split, args.version)
        if not args.overwrite:
            frames = [f for f in frames if not (DET_DIR / f"{f['sample']}.json").exists()]
        print(f'running YOLO on {len(frames)} frames ...')
        dets = detect(frames, args.weights)
        n = write(dets, True)
        for f in frames:  # frames where YOLO saw nothing still get a (empty) cache entry
            p = DET_DIR / f"{f['sample']}.json"
            if not p.exists():
                p.write_text('[]', encoding='utf-8')
        print(f'{n} samples with detections written')


if __name__ == '__main__':
    main()
