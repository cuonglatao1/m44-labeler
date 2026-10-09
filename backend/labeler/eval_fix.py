"""How often does applying the fix suggestion repair a flagged labelling error?

Errors with known answers are injected into clean GT (m44.inject: shift 1-2.5 m, size x0.6/x1.6, turn 90°, class swap,
delete). For every injected error the checker flags, the suggestion for that flag is applied and the result is graded
with the pilot rule (labeler/score.same_object: center 0.7 m, sides 25 %, heading 20°). Flags on untouched cuboids
(false alarms) are checked too: applying their suggestion must not break a correct cuboid.

  python -m labeler.eval_fix --split val
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from m44.geometry import project_frame
from m44.inject import inject
from m44.loader import load_frames_nusc
from m44.match import COMPATIBLE, DEFAULT_CFG, check, load_cfg

from .fix import suggest
from .propose import Sweep
from .score import same_object

ROOT = Path(__file__).resolve().parents[2]


def apply(s: dict, boxes: list[dict]) -> list[dict]:
    if s['action'] == 'update':
        return [{**b, **s['box']} if b['box_id'] == s['box_id'] else b for b in boxes]
    if s['action'] == 'set_class':
        return [{**b, 'cls': s['cls']} if b['box_id'] == s['box_id'] else b for b in boxes]
    if s['action'] == 'delete':
        return [b for b in boxes if b['box_id'] != s['box_id']]
    if s['action'] == 'create':
        return boxes + [{**s['box'], 'box_id': 'created'}]
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--max-frames', type=int)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    frames = load_frames_nusc(args.nusc_root, args.split)[:args.max_frames]
    eligible = {b['box_id'] for f in frames for b in f['boxes']
                if b['cls'] in COMPATIBLE and (b.get('visibility') or 0) >= 3 and np.hypot(*b['center'][:2]) <= 40}
    noisy, injected = inject(frames, eligible, seed=args.seed)
    err_of = {(e['sample'], e['box_id']): e['type'] for e in injected}

    stats = defaultdict(Counter)   # error type -> flagged / fixed / action counts
    harm = Counter()
    for f_clean, f in zip(frames, noisy):
        p = ROOT / 'cache' / 'dets' / f"{f['sample']}.json"
        dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        sweep = Sweep(np.fromfile(f['lidar_path'], dtype=np.float32).reshape(-1, 5)[:, :4])
        gt = {b['box_id']: b for b in f_clean['boxes']}
        flags, _ = check(project_frame(f), dets, cfg)
        seen = set()
        for fl in flags:
            key = fl['box_id'] or ('det', fl['cam'], tuple(fl['det_bbox']))
            if key in seen:
                continue
            seen.add(key)
            s = suggest(fl, f['boxes'], f, dets, sweep, cfg)
            after = apply(s, f['boxes'])
            if fl['type'] == 'MISSING_3D':
                deleted = [gt[b] for (smp, b), t in err_of.items() if smp == f['sample'] and t == 'DELETE']
                if not deleted:
                    harm['missing_false'] += 1
                    harm['missing_false_created'] += s['action'] == 'create'
                    continue
                created = [b for b in after if b['box_id'] == 'created']
                stats['DELETE']['flagged'] += 1
                stats['DELETE'][s['action']] += 1
                stats['DELETE']['fixed'] += bool(created and any(same_object(g, created[0]) is not None for g in deleted))
                continue
            etype = err_of.get((f['sample'], fl['box_id']))
            new = next((b for b in after if b['box_id'] == fl['box_id']), None)
            if etype is None:  # false alarm on a correct cuboid
                harm['clean_flagged'] += 1
                harm[f'clean_{s["action"]}' + (f'_{s["confidence"]}' if s.get('confidence') else '')] += 1
                harm['clean_broken'] += new is None or same_object(gt[fl['box_id']], new) is None
                continue
            stats[etype]['flagged'] += 1
            act = s['action'] + (f"_{s['confidence']}" if s.get('confidence') else '')
            ok = new is not None and same_object(gt[fl['box_id']], new) is not None
            stats[etype][act] += 1
            stats[etype]['fixed'] += ok
            if act.startswith('update'):
                stats[etype][f'{act}_fixed'] += ok

    print(f'{len(frames)} {args.split} frames, {len(injected)} injected errors (seed {args.seed})\n')
    print(f"{'error':<12}{'flagged':>9}{'fixed':>8}{'fixed %':>9}   suggested actions")
    tot_f = tot_x = 0
    for etype in ('OFFSET', 'SCALE', 'ROTATE', 'CLASS_SWAP', 'DELETE'):
        c = stats[etype]
        if not c['flagged']:
            continue
        tot_f += c['flagged']; tot_x += c['fixed']
        acts = ', '.join(f'{k} {v}' for k, v in c.items() if k not in ('flagged', 'fixed'))
        print(f"{etype:<12}{c['flagged']:>9}{c['fixed']:>8}{c['fixed'] / c['flagged']:>9.0%}   {acts}")
    print(f"{'all':<12}{tot_f:>9}{tot_x:>8}{tot_x / max(tot_f, 1):>9.0%}")
    n = harm['clean_flagged']
    print(f"\nfalse alarms on correct cuboids: {n}; suggestions: "
          + ', '.join(f"{k[6:]} {v}" for k, v in harm.items() if k.startswith('clean_') and k not in ('clean_flagged', 'clean_broken'))
          + f"; applying them would break {harm['clean_broken']} ({harm['clean_broken'] / max(n, 1):.0%})")
    print(f"MISSING_3D without a deleted cuboid: {harm['missing_false']} (a cuboid would be created for {harm['missing_false_created']})")


if __name__ == '__main__':
    main()
