"""What does one key press (Shift+G on an empty frame) give an annotator, graded with the pilot rules?

Per frame: start from no cuboids, propose for every MISSING_3D flag (exactly what the app does), optionally
repeat once on the flags that are left, and grade the result against the pilot targets.

  python -m labeler.eval_assist --split val            # every val frame
  python -m labeler.eval_assist --split val --frame 25 # the pilot labelling frame
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np

from m44.geometry import project_frame
from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, check, load_cfg

from .propose import Sweep, propose_missing
from .score import summary

ROOT = Path(__file__).resolve().parents[2]


def assist(frame: dict, dets: list[dict], cfg: dict, rounds: int = 1) -> list[dict]:
    """Cuboids after pressing Shift+G `rounds` times on an empty frame (no manual edits)."""
    sweep = Sweep(np.fromfile(frame['lidar_path'], dtype=np.float32).reshape(-1, 5)[:, :4])
    boxes: list[dict] = []
    for r in range(rounds):
        flags, _ = check(project_frame({**frame, 'boxes': boxes}), dets, cfg)
        new = propose_missing(sweep, frame['cams'], flags, boxes)
        boxes += [{**p, 'box_id': f'p{r}_{k}'} for k, p in enumerate(new)]
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--frame', type=int, help='only this frame index of the split')
    ap.add_argument('--rounds', type=int, default=1)
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--out', help='write per-frame results as JSON')
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    frames = load_frames_nusc(args.nusc_root, args.split)
    idx = [args.frame] if args.frame is not None else range(len(frames))
    rows = []
    for i in idx:
        f = frames[i]
        p = ROOT / 'cache' / 'dets' / f"{f['sample']}.json"
        dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        s = summary(f['boxes'], assist(f, dets, cfg, args.rounds))
        s.pop('box_status'), s.pop('target_status')
        rows.append({'frame': i, 'sample': f['sample'], **s})

    tot = {k: sum(r[k] for r in rows) for k in ('targets', 'target_correct', 'target_rough', 'target_missed',
                                                 'labelled', 'correct', 'rough', 'wrong')}
    print(f'{len(rows)} {args.split} frame(s), Shift+G on an empty frame ({args.rounds} round(s)), pilot grading:')
    print(f"  targets {tot['targets']}: correct {tot['target_correct']} ({tot['target_correct'] / max(tot['targets'], 1):.0%}), "
          f"rough {tot['target_rough']} ({tot['target_rough'] / max(tot['targets'], 1):.0%}), "
          f"missed {tot['target_missed']} ({tot['target_missed'] / max(tot['targets'], 1):.0%})")
    print(f"  proposed car/pedestrian cuboids {tot['labelled']}: correct {tot['correct']}, rough {tot['rough']}, "
          f"wrong {tot['wrong']}")
    if args.out:
        Path(args.out).write_text(json.dumps({'rows': rows, 'total': tot}, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
