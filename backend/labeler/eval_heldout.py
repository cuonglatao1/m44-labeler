"""Held-out test on the full nuScenes val split (150 scenes minus the ones in nuScenes-mini), with the thresholds tuned on
mini train left untouched (configs/lidar_qc.json). Only the nuScenes metadata is needed (v1.0-trainval_meta.tgz): it
holds every annotation and every ego pose, which is all the checks below use – no LiDAR sweep, no camera image.

  temporal  TRACK_SIZE / TRACK_JUMP / TRACK_YAW / TRACK_CLASS (labeler/track.py), with the nuScenes instance tokens or
            (--no-instance) linking cuboids by position only, as for cuboids drawn in the app
  size      SIZE_IMPLAUSIBLE (class size ranges + margin, labeler/lidar_qc.size_outliers)
  overlap   BEV_OVERLAP (two cuboids sharing their footprint)
  copy      "copy the cuboids from the previous frame" (labeler/propagate.py, the app setting: ego motion + velocity)

Errors are injected as in every other evaluation (m44.inject: shift 1-2.5 m, size x0.6 / x1.6, turn 90°, class swap,
30 % of the cuboids of every frame, seed 0); false alarms are counted on clean GT. Results are split by day / night /
rain (scene description).

  python -m labeler.eval_heldout --nusc-root D:/data/nuscenes-trainval
"""
import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from m44.inject import SWAP_TO, inject
from m44.loader import load_frames_nusc

from . import lidar_qc, track
from .calib_lidar import frames_by_scene
from .eval_propagate import grade
from .propagate import propagate

TYPES = ('TRACK_SIZE', 'TRACK_JUMP', 'TRACK_YAW', 'TRACK_CLASS', 'SIZE_IMPLAUSIBLE', 'BEV_OVERLAP')
ERRORS = ('OFFSET', 'SCALE', 'ROTATE', 'CLASS_SWAP')


def checks(frames, k, nb, gt_inst, cfg) -> tuple[dict, dict]:
    """{box_id: set of flag types} and {box_id: checked by the temporal check} for frame k."""
    f = frames[k]
    out = defaultdict(set)
    tf, ti = track.track_check(f, f['boxes'], [(frames[j], frames[j]['boxes']) for j in nb[k]], gt_inst, cfg['track'])
    for x in tf:
        out[x['box_id']].add(x['type'])
    for b in f['boxes']:
        if lidar_qc.size_outliers(b, cfg):
            out[b['box_id']].add('SIZE_IMPLAUSIBLE')
    for a, b, _ in lidar_qc.overlaps(f['boxes'], cfg['overlap']):
        out[a['box_id']].add('BEV_OVERLAP')
        out[b['box_id']].add('BEV_OVERLAP')
    return out, {bid: v['checked'] for bid, v in ti.items()}


def pct(a, b):
    return f'{a / b:.0%}' if b else '–'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nusc-root', default='D:/data/nuscenes-trainval')
    ap.add_argument('--version', default='v1.0-trainval')
    ap.add_argument('--no-instance', action='store_true')
    ap.add_argument('--max-scenes', type=int)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--json', help='also write the numbers here')
    args = ap.parse_args()

    from nuscenes.utils.splits import create_splits_scenes
    splits = create_splits_scenes()
    mini = set(splits['mini_train']) | set(splits['mini_val'])
    scenes = json.loads((Path(args.nusc_root) / args.version / 'scene.json').read_text(encoding='utf-8'))
    keep = [s for s in scenes if s['name'] in splits['val'] and s['name'] not in mini][:args.max_scenes]
    cond = {}
    for s in keep:
        d = s['description'].lower()
        cond[s['token']] = 'night' if 'night' in d else 'rain' if 'rain' in d else 'day'
    samples = set()
    sample_tab = json.loads((Path(args.nusc_root) / args.version / 'sample.json').read_text(encoding='utf-8'))
    for smp in sample_tab:
        if smp['scene_token'] in cond:
            samples.add(smp['token'])
    t0 = time.time()
    clean = load_frames_nusc(args.nusc_root, 'all', args.version, samples=samples)
    print(f"{len(keep)} held-out val scenes ({Counter(cond.values())}), {len(clean)} keyframes, "
          f"{sum(len(f['boxes']) for f in clean)} cuboids; loaded in {time.time() - t0:.0f} s", flush=True)

    cfg = lidar_qc.load_cfg()
    eligible = {b['box_id'] for f in clean for b in f['boxes'] if b['cls'] in SWAP_TO}
    noisy, injected = inject(clean, eligible, seed=args.seed)
    err = {(e['sample'], e['box_id']): e['type'] for e in injected}
    gt_inst = {b['box_id']: b['instance'] for f in clean for b in f['boxes']}
    if args.no_instance:
        gt_inst = {}
        for f in clean + noisy:
            for b in f['boxes']:
                b.pop('instance', None)
    nb = frames_by_scene(clean)

    fa = defaultdict(Counter)       # condition -> flag type -> flags on clean GT
    frames_n = Counter()
    boxes_n, covered = Counter(), Counter()
    caught = defaultdict(Counter)   # (condition, error) -> n / caught by temporal / size+overlap / any
    for k, (fc, fn) in enumerate(zip(clean, noisy)):
        c = cond[fc['scene']]
        frames_n[c] += 1
        flags_c, checked = checks(clean, k, nb, gt_inst, cfg)
        for types in flags_c.values():
            for t in types:
                fa[c][t] += 1
        boxes_n[c] += len(fc['boxes'])
        covered[c] += sum(checked.values())
        flags_n, _ = checks(noisy, k, nb, gt_inst, cfg)
        for (smp, bid), etype in err.items():
            if smp != fc['sample'] or etype == 'DELETE':
                continue
            types = flags_n.get(bid, set())
            cc = caught[(c, etype)]
            cc['n'] += 1
            cc['temporal'] += bool(types & {'TRACK_SIZE', 'TRACK_JUMP', 'TRACK_YAW', 'TRACK_CLASS'})
            cc['size_overlap'] += bool(types & {'SIZE_IMPLAUSIBLE', 'BEV_OVERLAP'})
            cc['any'] += bool(types)
        if (k + 1) % 1000 == 0:
            print(f'  {k + 1}/{len(clean)} frames', flush=True)

    # copy from the previous (correct) frame
    copy = defaultdict(Counter)
    moving = defaultdict(Counter)
    if not args.no_instance:
        scenes_f = defaultdict(list)
        for f in clean:
            scenes_f[f['scene']].append(f)
        for tok, fs in scenes_f.items():
            fs.sort(key=lambda f: f['timestamp'])
            for k in range(1, len(fs)):
                older = (fs[k - 2], fs[k - 2]['boxes']) if k >= 2 else None
                copies, _ = propagate(fs[k], (fs[k - 1], fs[k - 1]['boxes']), older, [], None)
                copy[cond[tok]].update(grade(copies, fs[k]['boxes']))

    conds = [c for c in ('day', 'rain', 'night') if frames_n[c]]
    print('\n' + ('objects linked by position only (as when drawn in the app)' if args.no_instance
                  else 'objects linked by nuScenes instance token'))
    print(f"\n{'':<34}" + ''.join(f'{c:>10}' for c in conds) + f"{'all':>10}")
    print(f"{'keyframes':<34}" + ''.join(f'{frames_n[c]:>10}' for c in conds) + f"{sum(frames_n.values()):>10}")
    print(f"{'temporal check coverage':<34}" + ''.join(f'{pct(covered[c], boxes_n[c]):>10}' for c in conds)
          + f"{pct(sum(covered.values()), sum(boxes_n.values())):>10}")
    for t in TYPES:
        print(f"{'FA / frame ' + t:<34}" + ''.join(f'{fa[c][t] / frames_n[c]:>10.2f}' for c in conds)
              + f"{sum(fa[c][t] for c in conds) / sum(frames_n.values()):>10.2f}")
    print(f"{'FA / frame, all these checks':<34}" + ''.join(f'{sum(fa[c].values()) / frames_n[c]:>10.2f}' for c in conds)
          + f"{sum(sum(fa[c].values()) for c in conds) / sum(frames_n.values()):>10.2f}")
    for e in ERRORS:
        for src in ('temporal', 'size_overlap', 'any'):
            row = [caught[(c, e)] for c in conds]
            tot = Counter()
            for r in row:
                tot.update(r)
            print(f"{'recall ' + e + ' (' + src + ')':<34}" + ''.join(f'{pct(r[src], r["n"]):>10}' for r in row)
                  + f"{pct(tot[src], tot['n']):>10}")
    tot_all = Counter()
    for v in caught.values():
        tot_all.update(v)
    print(f"{'recall all errors (any)':<34}" + ''.join(
        f"{pct(sum(caught[(c, e)]['any'] for e in ERRORS), sum(caught[(c, e)]['n'] for e in ERRORS)):>10}" for c in conds)
        + f"{pct(tot_all['any'], tot_all['n']):>10}")
    if copy:
        print('\ncopy from the previous frame (Ctrl+B, ego motion + velocity), share of copies of objects still annotated:')
        for c in conds + ['all']:
            g = Counter()
            for cc in ([copy[c]] if c != 'all' else copy.values()):
                g.update(cc)
            kept = g['correct'] + g['rough'] + g['off']
            print(f"  {c:<6} correct {pct(g['correct'], kept)}, rough {pct(g['rough'], kept)}, off {pct(g['off'], kept)}; "
                  f"new objects to draw {pct(g['new'], g['objects'])}, copies to delete {pct(g['gone'], kept + g['gone'])}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            'scenes': len(keep), 'frames': dict(frames_n), 'boxes': dict(boxes_n), 'covered': dict(covered),
            'false_alarms': {c: dict(v) for c, v in fa.items()},
            'recall': {f'{c}/{e}': dict(v) for (c, e), v in caught.items()},
            'copy': {c: dict(v) for c, v in copy.items()}, 'no_instance': args.no_instance}, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
