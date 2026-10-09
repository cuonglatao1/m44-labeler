"""How good is "copy the cuboids from the previous frame" (labeler/propagate.py)?

The annotator is simulated as finishing each keyframe exactly (= GT) before moving on: the GT cuboids of frame k-1 (and
k-2 for velocities) are propagated into frame k and every copy is graded against the same object's GT cuboid in frame k
with the pilot rule (labeler/score.same_object: center 0.7 m, sides 25 %, heading 20°):
  correct   – nothing to do
  rough     – right object within 2 m, needs a nudge
  off       – farther than that
  gone      – the object is not annotated in frame k any more: the copy has to be deleted
  new       – objects of frame k with no copy (appeared): still drawn by hand
Variants show what each step adds: raw copy (no ego compensation), + ego motion, + object velocity (the app), and the
LiDAR snap the app leaves off.
--chain N: no correction between frames, copies of copies for N frames (drift).

  python -m labeler.eval_propagate --split val
"""
import argparse
import math
import os
from collections import Counter, defaultdict

import numpy as np

from m44.loader import load_frames_nusc

from .propagate import propagate
from .propose import Sweep
from .score import same_object

VARIANTS = {
    'raw copy (no ego motion)': None,
    '+ ego motion': {'use_motion': False, 'use_snap': False},
    '+ object velocity (app)': {'use_motion': True, 'use_snap': False},
    '+ LiDAR snap (not used)': {'use_motion': True, 'use_snap': True},
}


def grade(copies: list[dict], gt: list[dict]) -> Counter:
    by_inst = {b['instance']: b for b in gt}
    c = Counter()
    for b in copies:
        g = by_inst.get(b['instance'])
        if g is None:
            c['gone'] += 1
        elif same_object(g, b) is not None:
            c['correct'] += 1
        elif math.dist(g['center'][:2], b['center'][:2]) <= 2.0:
            c['rough'] += 1
        else:
            c['off'] += 1
    copied = {b['instance'] for b in copies}
    c['new'] = sum(1 for g in gt if g['instance'] not in copied)
    c['objects'] = len(gt)
    return c


def raw_copy(prev_boxes: list[dict]) -> list[dict]:
    return [{**b, 'instance': b['instance']} for b in prev_boxes]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--chain', type=int, default=0, help='also propagate copies of copies for N frames')
    args = ap.parse_args()

    frames = load_frames_nusc(args.nusc_root, args.split)
    scenes = defaultdict(list)
    for f in frames:
        scenes[f['scene']].append(f)
    for fs in scenes.values():
        fs.sort(key=lambda f: f['timestamp'])

    res = {v: Counter() for v in VARIANTS}
    by_class = defaultdict(Counter)
    moving = Counter()
    chain = defaultdict(Counter)
    for fs in scenes.values():
        sweeps = {}
        for k in range(1, len(fs)):
            cur, prev = fs[k], fs[k - 1]
            older = (fs[k - 2], fs[k - 2]['boxes']) if k >= 2 else None
            if k not in sweeps:
                sweeps[k] = Sweep(np.fromfile(cur['lidar_path'], dtype=np.float32).reshape(-1, 5))
            for name, kw in VARIANTS.items():
                if kw is None:
                    copies = raw_copy(prev['boxes'])
                else:
                    copies, _ = propagate(cur, (prev, prev['boxes']), older, [], sweeps[k], **kw)
                g = grade(copies, cur['boxes'])
                res[name].update(g)
                if kw and kw['use_motion'] and not kw['use_snap']:  # the app setting
                    gt_k = {b['instance']: b for b in cur['boxes']}
                    gt_p = {b['instance']: b for b in prev['boxes']}
                    for b in copies:
                        gk, gp = gt_k.get(b['instance']), gt_p.get(b['instance'])
                        if gk is None:
                            continue
                        ok = same_object(gk, b) is not None
                        by_class[gk['cls']]['n'] += 1
                        by_class[gk['cls']]['correct'] += ok
                        # moving = the object itself moved more than 0.5 m in the world between the two frames
                        gw = lambda f, x: (np.asarray(f['lidar2global']) @ np.r_[x['center'], 1.0])[:2]  # noqa: E731
                        key = 'moving' if gp and np.hypot(*(gw(cur, gk) - gw(prev, gp))) > 0.5 else 'static'
                        moving[f'{key}_n'] += 1
                        moving[f'{key}_correct'] += ok
            if args.chain and k == 1:
                # copies of copies from the first frame, no correction
                labels = {0: fs[0]['boxes']}
                for step in range(1, min(args.chain, len(fs) - 1) + 1):
                    sw = sweeps.get(step) or Sweep(np.fromfile(fs[step]['lidar_path'], dtype=np.float32).reshape(-1, 5))
                    sweeps[step] = sw
                    older = (fs[step - 2], labels[step - 2]) if step >= 2 else None
                    labels[step], _ = propagate(fs[step], (fs[step - 1], labels[step - 1]), older, [], sw)
                    chain[step].update(grade(labels[step], fs[step]['boxes']))

    n_frames = sum(len(fs) - 1 for fs in scenes.values())
    print(f'{len(scenes)} {args.split} scenes, {n_frames} frames propagated from the previous (correct) frame\n')
    print(f"{'':<28}{'copies':>8}{'correct':>9}{'rough':>8}{'off':>6}{'gone':>7}   objects: new (to draw)")
    for name, c in res.items():
        n = c['correct'] + c['rough'] + c['off'] + c['gone']
        kept = c['correct'] + c['rough'] + c['off']
        print(f"{name:<28}{n:>8}{c['correct'] / kept:>9.0%}{c['rough'] / kept:>8.0%}{c['off'] / kept:>6.0%}"
              f"{c['gone']:>7}   {c['objects']}: {c['new']} ({c['new'] / c['objects']:.0%})")
    print('\n(correct / rough / off = share of copies whose object is still annotated)')
    print('\nApp setting by class: ' + ', '.join(f"{k} {v['correct'] / v['n']:.0%} of {v['n']}"
                                                for k, v in sorted(by_class.items(), key=lambda kv: -kv[1]['n'])))
    print(f"Static objects {moving['static_correct'] / max(moving['static_n'], 1):.0%} correct ({moving['static_n']}), "
          f"moving {moving['moving_correct'] / max(moving['moving_n'], 1):.0%} ({moving['moving_n']})")
    if chain:
        print('\nNo correction (copies of copies):')
        for step, c in sorted(chain.items()):
            kept = c['correct'] + c['rough'] + c['off']
            print(f"  after {step} frame(s): {c['correct'] / kept:.0%} correct, {c['rough'] / kept:.0%} rough")


if __name__ == '__main__':
    main()
