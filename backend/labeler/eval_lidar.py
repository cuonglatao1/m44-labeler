"""Camera vs LiDAR vs temporal QC on the same injected errors (M44 protocol), reported separately for the cuboids the
camera check cannot verify.

Errors with known answers are injected into clean GT with m44.inject (shift 1-2.5 m, size x0.6 / x1.6, turn 90°, class
swap, delete; 30 % of the cuboids of every class the swap table knows, seed 0) in every frame of the split, so the
temporal check sees corrupted neighbours too. An error is caught by a method when that method flags its cuboid
(DELETE: flagged as missing – camera MISSING_3D, or TRACK_MISSING / LIDAR_UNBOXED from labeler/missing.py). False alarms and coverage are measured on clean GT.

  python -m labeler.eval_lidar --split val
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from m44.geometry import project_frame
from m44.inject import SWAP_TO, inject
from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, check, load_cfg

from . import lidar_qc, missing, track
from .calib_lidar import frames_by_scene
from .eval_fix import apply
from .fix import suggest
from .inject_subtle import inject_subtle
from .propose import Sweep
from .qc import rank_flags
from .score import same_object

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('camera', 'lidar', 'track')
ORDER = ['OFFSET', 'SCALE', 'ROTATE', 'CLASS_SWAP', 'DELETE', 'SHIFT', 'YAW', 'FLIP', 'LENGTH', 'HEIGHT', 'CONFUSE']


def run(frames, k, sweep, cfg, lqc, gt_inst, nb, dets) -> dict:
    """All three checks on frame k of `frames`: flags with source, and per cuboid which sources could judge it."""
    f = frames[k]
    flags, matches = check(project_frame(f), dets, cfg)
    for x in flags:
        x['source'] = 'camera'
    lf, li = lidar_qc.lidar_check(f['boxes'], sweep, lqc)
    tf, ti = track.track_check(f, f['boxes'], [(frames[j], frames[j]['boxes']) for j in nb[k]], gt_inst, lqc['track'])
    flags += [{**x, 'source': 'lidar', 'cam': None} for x in lf] + [{**x, 'source': 'track', 'cam': None} for x in tf]
    miss = missing.track_missing(f, f['boxes'], [(frames[j], frames[j]['boxes']) for j in nb[k]], gt_inst, lqc['track'])
    miss, unboxed = missing.corroborate(miss, f, sweep, flags, lqc)
    flags += [{**x, 'source': 'track', 'cam': None} for x in miss] + [{**x, 'source': 'lidar', 'cam': None} for x in unboxed]
    flags = rank_flags(flags)
    cam_ok = {m['box_id'] for m in matches} | {x['box_id'] for x in flags if x['source'] == 'camera' and x['box_id']}
    covered = {b['box_id']: {'camera': b['box_id'] in cam_ok, 'lidar': li[b['box_id']]['checked'],
                             'track': ti[b['box_id']]['checked']} for b in f['boxes']}
    return {'flags': flags, 'covered': covered}


def pct(a, b):
    return f'{a / b:.0%}' if b else '–'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--max-frames', type=int)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--errors', choices=['m44', 'subtle'], default='m44',
                    help='m44: the large M44 errors (m44.inject); subtle: small human-like ones (labeler/inject_subtle.py)')
    ap.add_argument('--json', help='also write the numbers here')
    ap.add_argument('--no-instance', action='store_true',
                    help='hide the nuScenes instance tokens: the temporal check links cuboids by position only, as for '
                         'cuboids drawn in the app')
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    lqc = lidar_qc.load_cfg()
    clean = load_frames_nusc(args.nusc_root, args.split)[:args.max_frames]
    eligible = {b['box_id'] for f in clean for b in f['boxes'] if b['cls'] in SWAP_TO}
    if args.errors == 'subtle':
        noisy, injected = inject_subtle(clean, eligible, seed=args.seed)
    else:
        noisy, injected = inject(clean, eligible, seed=args.seed)
    etypes = [t for t in ORDER if any(e['type'] == t for e in injected)]
    err = {(e['sample'], e['box_id']): e['type'] for e in injected}
    gt_inst = {b['box_id']: b['instance'] for f in clean for b in f['boxes']}
    if args.no_instance:
        gt_inst = {}
        for f in clean + noisy:
            for b in f['boxes']:
                b.pop('instance', None)
    nb = frames_by_scene(clean)

    caught = defaultdict(Counter)       # (group, error type) -> counts per source / combined
    fa = Counter()                      # flags on clean GT per source / type
    fa_boxes = Counter()                # clean cuboids with at least one flag per source
    cover = Counter()                   # clean cuboids each source can judge
    cover_hard = Counter()              # same, among cuboids the camera cannot judge
    fixes = defaultdict(Counter)        # source -> flagged errors with a suggestion / fixed
    harm = Counter()
    sure = Counter()                    # certainty: flags on clean GT, on corrupted / untouched cuboids, errors caught
    n_boxes = n_hard = 0
    for k, (fc, fn) in enumerate(zip(clean, noisy)):
        p = ROOT / 'cache' / 'dets' / f"{fc['sample']}.json"
        dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        sweep = Sweep(np.fromfile(fc['lidar_path'], dtype=np.float32).reshape(-1, 5))
        rc = run(clean, k, sweep, cfg, lqc, gt_inst, nb, dets)
        rn = run(noisy, k, sweep, cfg, lqc, gt_inst, nb, dets)

        for x in rc['flags']:
            fa[(x['source'], x['type'])] += 1
            sure[f"clean_{x['certainty']}"] += 1
        for x in rn['flags']:
            if x.get('box_id'):
                bad = (fn['sample'], x['box_id']) in err
                sure[f"{x['certainty']}_{'error' if bad else 'ok'}"] += 1
        for src in SOURCES:
            fa_boxes[src] += len({x['box_id'] for x in rc['flags'] if x['source'] == src and x['box_id']})
        fa_boxes['any'] += len({x['box_id'] for x in rc['flags'] if x['box_id']})
        for bid, cv in rc['covered'].items():
            n_boxes += 1
            for src in SOURCES:
                cover[src] += cv[src]
            cover['any'] += any(cv.values())
            if not cv['camera']:
                n_hard += 1
                for src in ('lidar', 'track'):
                    cover_hard[src] += cv[src]
                cover_hard['any'] += cv['lidar'] or cv['track']

        gt = {b['box_id']: b for b in fc['boxes']}
        # deleted cuboids: flagged as missing by which source (labeler/missing.py)?
        for (smp, bid), etype in err.items():
            if smp != fc['sample'] or etype != 'DELETE':
                continue
            grp = 'camera_ok' if rc['covered'][bid]['camera'] else 'camera_blind'
            srcs, is_sure = missing.missing_hits(rn['flags'], gt[bid], fc, gt_inst.get(bid))
            c = caught[(grp, 'DELETE')]
            c['n'] += 1
            for src in SOURCES:
                c[src] += src in srcs
            c['lidar+track'] += bool(srcs & {'lidar', 'track'})
            c['all'] += bool(srcs)
            c['sure'] += is_sure
        by_box = defaultdict(list)
        for x in rn['flags']:
            if x.get('box_id'):
                by_box[x['box_id']].append(x)
        for (smp, bid), etype in err.items():
            if smp != fc['sample'] or etype == 'DELETE':
                continue
            grp = 'camera_ok' if rc['covered'][bid]['camera'] else 'camera_blind'
            srcs = {x['source'] for x in by_box[bid]}
            c = caught[(grp, etype)]
            c['n'] += 1
            for src in SOURCES:
                c[src] += src in srcs
            c['lidar+track'] += bool(srcs & {'lidar', 'track'})
            c['all'] += bool(srcs)
            c['sure'] += len(srcs) >= 2
            # apply the suggestion of the first LiDAR / temporal flag on the error
            for src in ('track', 'lidar'):
                fl = next((x for x in by_box[bid] if x['source'] == src), None)
                if fl is None:
                    continue
                s = suggest(fl, fn['boxes'], fn, dets, sweep, cfg)
                new = next((b for b in apply(s, fn['boxes']) if b['box_id'] == bid), None)
                fixes[src]['flagged'] += 1
                fixes[src][s['action']] += 1
                fixes[src]['fixed'] += new is not None and same_object(gt[bid], new) is not None
        # suggestions on false alarms (clean GT): would applying them break a correct cuboid?
        for x in rc['flags']:
            if x['source'] == 'camera' or not x.get('box_id'):
                continue
            s = suggest(x, fc['boxes'], fc, dets, sweep, cfg)
            new = next((b for b in apply(s, fc['boxes']) if b['box_id'] == x['box_id']), None)
            harm['flags'] += 1
            harm[s['action']] += 1
            harm['broken'] += new is None or same_object(gt[x['box_id']], new) is None
        if (k + 1) % 20 == 0:
            print(f'  {k + 1}/{len(clean)} frames', flush=True)

    nf = len(clean)
    print(f'\n{nf} {args.split} frames, {n_boxes} GT cuboids, {len(injected)} injected {args.errors} errors (seed {args.seed})'
          + (', objects linked by position only' if args.no_instance else '') + '\n')
    print('Coverage on clean GT (share of cuboids a source can judge)')
    print(f"  all cuboids          camera {pct(cover['camera'], n_boxes)}  lidar {pct(cover['lidar'], n_boxes)}  "
          f"track {pct(cover['track'], n_boxes)}  any {pct(cover['any'], n_boxes)}")
    print(f"  camera cannot judge  {n_hard} cuboids ({pct(n_hard, n_boxes)}): lidar {pct(cover_hard['lidar'], n_hard)}  "
          f"track {pct(cover_hard['track'], n_hard)}  lidar or track {pct(cover_hard['any'], n_hard)}")
    print('\nFalse alarms on clean GT (flags per frame / cuboids flagged)')
    for src in SOURCES:
        n = sum(v for (s, _), v in fa.items() if s == src)
        types = ', '.join(f'{t} {v}' for (s, t), v in sorted(fa.items()) if s == src)
        print(f'  {src:<7} {n / nf:5.2f} / frame, {pct(fa_boxes[src], n_boxes)} of cuboids   ({types})')
    print(f"  any     {sum(fa.values()) / nf:5.2f} / frame, {pct(fa_boxes['any'], n_boxes)} of cuboids")
    for grp, title in (('camera_ok', 'cuboids the camera can judge'), ('camera_blind', 'cuboids the camera CANNOT judge')):
        print(f'\nRecall – {title}')
        print(f"  {'error':<12}{'n':>6}{'camera':>9}{'lidar':>8}{'track':>8}{'L+T':>8}{'all':>8}")
        tot = Counter()
        for etype in etypes:
            c = caught[(grp, etype)]
            tot.update(c)
            print(f"  {etype:<12}{c['n']:>6}" + ''.join(f'{pct(c[s], c["n"]):>{w}}' for s, w in
                                                   (('camera', 9), ('lidar', 8), ('track', 8), ('lidar+track', 8), ('all', 8))))
        print(f"  {'all':<12}{tot['n']:>6}" + ''.join(f'{pct(tot[s], tot["n"]):>{w}}' for s, w in
                                                (('camera', 9), ('lidar', 8), ('track', 8), ('lidar+track', 8), ('all', 8))))
    print('\nFix suggestions on flagged errors (graded: center 0.7 m, sides 25 %, heading 20°)')
    for src in ('lidar', 'track'):
        c = fixes[src]
        acts = ', '.join(f'{k} {v}' for k, v in c.items() if k not in ('flagged', 'fixed'))
        print(f"  {src:<6} {c['fixed']}/{c['flagged']} fixed ({pct(c['fixed'], c['flagged'])})   {acts}")
    print('\nCertainty (labeler/qc.py: high = flagged by >= 2 sources)')
    for lv, name in (('high', 'sure  '), ('review', 'review')):
        n_err, n_ok = sure[f'{lv}_error'], sure[f'{lv}_ok']
        print(f"  {name}: on corrupted data {n_err + n_ok} cuboid flags, {pct(n_err, n_err + n_ok)} on a real error; "
              f"on clean GT {sure[f'clean_{lv}'] / nf:.2f} flags / frame")
    tot = Counter()
    for c in caught.values():
        tot.update(c)
    print(f"  errors caught by a sure flag: {pct(tot['sure'], tot['n'])} (any flag: {pct(tot['all'], tot['n'])})")
    acts = ', '.join(f'{k} {v}' for k, v in harm.items() if k not in ('flags', 'broken'))
    print(f"  on false alarms: {harm['flags']} suggestions ({acts}); applying them would break {harm['broken']} "
          f"({pct(harm['broken'], harm['flags'])})")
    if args.json:
        Path(args.json).write_text(json.dumps({
            'frames': nf, 'boxes': n_boxes, 'injected': len(injected), 'coverage': dict(cover),
            'coverage_camera_blind': {**cover_hard, 'n': n_hard},
            'false_alarms': {f'{s}/{t}': v for (s, t), v in fa.items()},
            'recall': {f'{g}/{e}': dict(c) for (g, e), c in caught.items()},
            'fixes': {s: dict(c) for s, c in fixes.items()}, 'harm': dict(harm), 'certainty': dict(sure)}, indent=1),
            encoding='utf-8')


if __name__ == '__main__':
    main()
