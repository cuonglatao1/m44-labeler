"""Calibrate the LiDAR and temporal QC thresholds on clean GT (train), and show what each threshold catches.

For every GT cuboid the evidence (labeler/lidar_qc.py, labeler/track.py) is measured as is and on corrupted copies of
the same cuboid (shift 1-2.5 m, size x0.6 / x1.6, turn 90°, class swap – the M44 error types – plus raised / lowered
0.6 m). Each check is tuned per class group: the setting with the best recall on the corrupted copies whose false-alarm
rate on the clean cuboids stays within a budget (default 0.5 % per check). Temporal thresholds get floors because GT
tracks are almost perfectly consistent.

  python -m labeler.calib_lidar --split train            # writes configs/lidar_qc.json
  python -m labeler.calib_lidar --split train --dry-run  # only print
"""
import argparse
import json
import math
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from m44.inject import SWAP_TO
from m44.loader import load_frames_nusc

from . import lidar_qc as lq
from . import track as tr
from .propose import Sweep

ROOT = Path(__file__).resolve().parents[2]

GROUPS = ('vehicle', 'pedestrian', 'two_wheeler', 'static')
VARIANTS = ('clean', 'OFFSET', 'SCALE_0.6', 'SCALE_1.6', 'ROTATE', 'CLASS_SWAP', 'Z_SHIFT')
OBSERVABLE = 10  # LiDAR points inside the correct cuboid needed for the ray / point checks to have a chance


def corrupt(box: dict, kind: str, rng: random.Random) -> dict | None:
    b = {**box, 'center': list(box['center']), 'size': list(box['size'])}
    if kind == 'OFFSET':
        d, a = rng.uniform(1.0, 2.5), rng.uniform(0, 2 * math.pi)
        b['center'][0] += d * math.cos(a)
        b['center'][1] += d * math.sin(a)
    elif kind.startswith('SCALE'):
        k = float(kind.split('_')[1])
        b['size'] = [v * k for v in b['size']]
    elif kind == 'ROTATE':
        if b['size'][0] / b['size'][1] < 1.5:
            return None
        b['yaw'] += math.pi / 2
    elif kind == 'Z_SHIFT':  # not an M44 error type: floating / sunken cuboids
        b['center'][2] += rng.choice([-0.6, 0.6])
    elif kind == 'CLASS_SWAP':
        if b['cls'] not in SWAP_TO:
            return None
        b['cls'] = SWAP_TO[b['cls']]
    return b


def frames_by_scene(frames: list[dict]) -> dict[int, list[int]]:
    """frame index -> indices of up to K_FRAMES neighbours before / after in the same scene."""
    scenes = defaultdict(list)
    for i, f in enumerate(frames):
        scenes[f['scene']].append(i)
    out = {}
    for ix in scenes.values():
        ix.sort(key=lambda i: frames[i]['timestamp'])
        for r, i in enumerate(ix):
            out[i] = ix[max(0, r - tr.K_FRAMES):r] + ix[r + 1:r + 1 + tr.K_FRAMES]
    return out


def measure(box: dict, sweep: Sweep, obs: list[dict], tcfg: dict) -> dict:
    ev = lq.box_evidence(box, sweep)
    rays = ev['rays'] or {}
    sup = rays.get('hit', 0) + rays.get('pass', 0)
    m = {'cls': box['cls'], 'g': lq.group(box['cls']), 'support': sup, 'hit': rays.get('hit', 0),
         'pass_frac': rays.get('pass', 0) / sup if sup else np.nan,
         'n_in': ev['n_inside'], 'n_spill': ev['n_spill'], 'n_body': ev['n_body'],
         'spill_frac': ev['n_spill'] / (ev['n_inside'] + ev['n_spill']) if ev['n_inside'] + ev['n_spill'] else np.nan,
         'ground_gap': ev['ground_gap'] if ev['ground_gap'] is not None else np.nan,
         'l': box['size'][0], 'w': box['size'][1], 'h': box['size'][2]}
    ax = ev.get('axis')
    m['heading_gap'] = np.nan
    if ax and ax['long'] >= 0.6 * lq.CLASS_SIZES[box['cls']][0] and ax['long'] >= 1.5 * ax['short']:
        m['heading_gap'] = lq._yaw_gap_deg(ax['yaw'], box['yaw'])
        m['heading_n'] = ax['n']
    st = tr.track_stats(box, obs, tcfg)
    m['n_obs'] = st['n_obs']
    m['size_dev'] = st.get('size_dev', np.nan)
    m['jump'] = st.get('jump', np.nan)
    m['yaw_gap'] = st.get('yaw_gap', np.nan) if (box['cls'] in lq.VEHICLES or box['cls'] in lq.TWO_WHEEL) else np.nan
    m['class_bad'] = float(st['major_cls'] != box['cls'] and st['major_share'] >= tcfg['class_share']) \
        if 'major_cls' in st else np.nan
    return m


def collect(frames: list[dict], seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    tcfg = dict(tr.DEFAULTS)
    nb = frames_by_scene(frames)
    gt_inst = {b['box_id']: b['instance'] for f in frames for b in f['boxes']}
    rows = []
    for i, f in enumerate(frames):
        sweep = Sweep(np.fromfile(f['lidar_path'], dtype=np.float32).reshape(-1, 5))
        others = [(frames[j], frames[j]['boxes']) for j in nb[i]]
        obs_all = tr.observations(f, f['boxes'], others, gt_inst)  # by instance: the same for every corrupted copy
        for b in f['boxes']:
            n_clean = None
            for kind in VARIANTS:
                bb = b if kind == 'clean' else corrupt(b, kind, rng)
                if bb is None:
                    continue
                m = measure(bb, sweep, obs_all[b['box_id']], tcfg)
                n_clean = m['n_in'] if kind == 'clean' else n_clean
                rows.append({'kind': kind, 'orig_cls': b['cls'], 'vis': b['visibility'], 'clean_in': n_clean,
                             'dist': float(np.hypot(*b['center'][:2])), **m})
        if (i + 1) % 25 == 0:
            print(f'  {i + 1}/{len(frames)} frames', flush=True)
    return rows


def q_hi(vals, q):
    v = np.asarray([x for x in vals if np.isfinite(x)])
    return float(np.quantile(v, q)) if len(v) else None


def _pick(clean: list[dict], bad: list[dict], fires, params, budget: float):
    """Parameters with the best recall on `bad` whose firing rate on `clean` stays within the budget."""
    best, best_rec = None, -1.0
    for p in params:
        fa = np.mean([fires(r, p) for r in clean]) if clean else 0.0
        if fa > budget:
            continue
        rec = np.mean([fires(r, p) for r in bad]) if bad else 0.0
        if rec > best_rec + 1e-9:
            best, best_rec = p, rec
    return best


def calibrate(rows: list[dict], budget: float) -> dict:
    """Thresholds tuned on clean / corrupted train cuboids: per check and class group, the setting with the highest
    recall (on cuboids the LiDAR sees: OBSERVABLE points in the correct cuboid) whose false-alarm rate on all clean
    cuboids of the group stays within `budget`."""
    clean = [r for r in rows if r['kind'] == 'clean']
    cfg = {k: v for k, v in lq.DEFAULTS.items()}
    by = defaultdict(list)
    for r in rows:
        by[(r['kind'], r['g'])].append(r)

    def bad(g, kinds):
        return [r for k in kinds for r in by[(k, g)] if r['clean_in'] >= OBSERVABLE]

    cfg['free'], cfg['spill'], cfg['ground'], cfg['heading'] = {}, {}, {}, {}
    grid = [round(float(x), 2) for x in np.arange(0.2, 0.96, 0.05)]
    for g in GROUPS:
        cl = by[('clean', g)]
        f = _pick(cl, bad(g, ('OFFSET', 'SCALE_1.6')),
                  lambda r, p: r['support'] >= p[0] and r['pass_frac'] > p[1],
                  [(s_, t) for s_ in (6, 10, 15, 20, 30) for t in grid], budget)
        cfg['free'][g] = list(f) if f else [30, 0.95]
        f = _pick(cl, bad(g, ('OFFSET', 'SCALE_0.6', 'ROTATE')),
                  lambda r, p: r['n_spill'] >= p[0] and r['spill_frac'] > p[1],
                  [(n, t) for n in (5, 8, 12, 20) for t in grid], budget)
        cfg['spill'][g] = list(f) if f else [20, 0.95]
        f = _pick(cl, bad(g, ('ROTATE',)),
                  lambda r, p: np.isfinite(r['heading_gap']) and r.get('heading_n', 0) >= p[0] and r['heading_gap'] > p[1],
                  [(n, d) for n in (15, 30, 50) for d in range(15, 61, 5)], budget)
        cfg['heading'][g] = list(f) if f else [50, 60]
        gg = np.asarray([r['ground_gap'] for r in cl if np.isfinite(r['ground_gap'])])
        if len(gg) >= 30:
            k = budget * len(cl) / len(gg)  # budget over all cuboids of the group, spent on the measurable ones
            lo, hi = np.quantile(gg, [min(k / 2, 0.5), max(1 - k / 2, 0.5)])
            cfg['ground'][g] = [round(float(min(lo, -0.3)), 2), round(float(max(hi, 0.3)), 2)]
        else:
            cfg['ground'][g] = lq.DEFAULTS['ground'][g]
    # empty cuboid: the smallest support at which "at most empty_max_hits hits" stays within the budget
    for s_ in range(4, 60):
        if np.mean([r['support'] >= s_ and r['hit'] <= cfg['empty_max_hits'] and r['n_body'] <= cfg['empty_max_hits'] + 1
                    for r in clean]) <= budget:
            cfg['empty_min_support'] = s_
            break
    # temporal: nuScenes GT tracks are almost perfectly consistent, so the clean quantiles are tiny; floors keep room
    # for an annotator's normal jitter
    t = dict(tr.DEFAULTS)
    q = 1 - budget
    t['size_dev'] = round(max(q_hi([r['size_dev'] for r in clean], q) or 0.1, 0.08), 3)
    t['jump_m'] = {g: round(max(q_hi([r['jump'] for r in by[('clean', g)]], q) or 0.8,
                                0.5 if g in ('vehicle', 'two_wheeler') else 0.4), 2) for g in GROUPS}
    t['yaw_deg'] = round(max(q_hi([r['yaw_gap'] for r in clean], q) or 25.0, 15.0), 1)
    cfg['track'] = t
    return cfg


def _size_bounds(boxes: list[dict]) -> dict:
    """{cls: {l|w|h: [lo, hi]}}: 0.5-99.5 % of the GT sizes (rare classes: observed range widened by 15 %)."""
    out = {}
    for cls in sorted({b['cls'] for b in boxes}):
        v = np.asarray([b['size'] for b in boxes if b['cls'] == cls])
        d = {}
        for k, name in enumerate('lwh'):
            if len(v) >= 30:
                lo, hi = np.quantile(v[:, k], [0.005, 0.995])
            else:
                lo, hi = v[:, k].min() / 1.15, v[:, k].max() * 1.15
            d[name] = [round(float(lo), 3), round(float(hi), 3)]
        out[cls] = d
    return out


def calibrate_sizes(frames: list[dict], budget: float, folds: int = 10) -> tuple[dict, float]:
    """Class size ranges and the margin around them. nuScenes repeats the same objects in every frame of a scene, so the
    margin is chosen scene-out: the scenes are split in `folds` groups (leave-one-scene-out when there are fewer) and
    the margin is the smallest at which the ranges learnt from the other groups flag at most `budget` of the cuboids
    of the held-out group (pooled)."""
    by_scene = defaultdict(list)
    for f in frames:
        by_scene[f['scene']] += f['boxes']
    names = sorted(by_scene)
    k = min(folds, len(names))
    groups = [names[i::k] for i in range(k)]
    held = []
    for g in groups:
        gs = set(g)
        held.append((_size_bounds([b for t, bs in by_scene.items() if t not in gs for b in bs]),
                     [b for t in g for b in by_scene[t]]))
    margin = 1.4
    for m in np.arange(1.0, 1.41, 0.025):
        cfg = {'size_margin': float(m)}
        n = bad = 0
        for bounds, boxes in held:
            cfg['size'] = bounds
            for b in boxes:
                n += 1
                bad += bool(lq.size_outliers(b, cfg))
        if bad <= budget * n:
            margin = float(m)
            break
    return _size_bounds([b for f in frames for b in f['boxes']]), round(margin, 3)


def flags_of(r: dict, cfg: dict) -> set[str]:
    """Which checks fire for one measured cuboid (same rules as lidar_qc.judge / track.judge)."""
    out = set()
    g = r['g']
    if r['support'] >= cfg['empty_min_support'] and r['hit'] <= cfg['empty_max_hits'] \
            and r['n_body'] <= cfg['empty_max_hits'] + 1:
        out.add('LIDAR_EMPTY')
    elif r['support'] >= cfg['free'][g][0] and r['pass_frac'] > cfg['free'][g][1]:
        out.add('LIDAR_FREE')
    if r['n_spill'] >= cfg['spill'][g][0] and r['spill_frac'] > cfg['spill'][g][1]:
        out.add('LIDAR_SPILL')
    if np.isfinite(r['heading_gap']) and r.get('heading_n', 0) >= cfg['heading'][g][0] and r['heading_gap'] > cfg['heading'][g][1]:
        out.add('LIDAR_HEADING')
    if lq.size_outliers({'cls': r['cls'], 'size': [r['l'], r['w'], r['h']]}, cfg):
        out.add('SIZE_IMPLAUSIBLE')
    lo, hi = cfg['ground'][g]
    if np.isfinite(r['ground_gap']) and not lo <= r['ground_gap'] <= hi:
        out.add('GROUND')
    t = cfg['track']
    if r['n_obs'] >= t['min_obs']:
        if r['size_dev'] > t['size_dev']:
            out.add('TRACK_SIZE')
        if np.isfinite(r['jump']) and r['jump'] > t['jump_m'][g]:
            out.add('TRACK_JUMP')
        if np.isfinite(r['yaw_gap']) and r['yaw_gap'] > t['yaw_deg']:
            out.add('TRACK_YAW')
        if r['class_bad'] == 1.0:
            out.add('TRACK_CLASS')
    return out


LIDAR = {'LIDAR_EMPTY', 'LIDAR_FREE', 'LIDAR_SPILL', 'LIDAR_HEADING', 'SIZE_IMPLAUSIBLE', 'GROUND'}
TRACK = {'TRACK_SIZE', 'TRACK_JUMP', 'TRACK_YAW', 'TRACK_CLASS'}


def report(rows: list[dict], cfg: dict, title: str = '') -> None:
    by_kind = defaultdict(list)
    for r in rows:
        by_kind[r['kind']].append(flags_of(r, cfg))
    checks = sorted(LIDAR | TRACK)
    print(f'\n{title}per-cuboid firing rate (clean = false alarms; others = recall)')
    print(f"{'check':<18}" + ''.join(f'{k:>12}' for k in VARIANTS))
    for c in checks:
        print(f'{c:<18}' + ''.join(f"{np.mean([c in s for s in by_kind[k]]):>12.1%}" for k in VARIANTS))
    for name, group_ in (('any LiDAR', LIDAR), ('any track', TRACK), ('any', LIDAR | TRACK)):
        print(f'{name:<18}' + ''.join(f"{np.mean([bool(s & group_) for s in by_kind[k]]):>12.1%}" for k in VARIANTS))
    print(f"{'n':<18}" + ''.join(f'{len(by_kind[k]):>12}' for k in VARIANTS))


def overlap_stats(frames: list[dict], cfg: dict) -> dict:
    """Clean-GT BEV_OVERLAP flags per frame by pair of classes with the class-pair rule (lidar_qc.pair_threshold)."""
    c = Counter()
    for f in frames:
        for a, b, _ in lq.overlaps(f['boxes'], cfg['overlap'], rule=cfg):
            c['|'.join(sorted((a['cls'], b['cls'])))] += 1
    return c


def relearn_annotation_thresholds(args) -> None:
    """v2 (D-020): class size ranges + margin from the train split of the full nuScenes (700 scenes) instead of the 8
    mini scenes; the overlap thresholds checked on the same split. LiDAR thresholds are kept."""
    from nuscenes.utils.splits import create_splits_scenes

    sp = create_splits_scenes()
    root = Path(args.annotations_from) / args.annotations_version
    train = {s['token'] for s in json.loads((root / 'scene.json').read_text(encoding='utf-8')) if s['name'] in sp['train']}
    samples = {s['token'] for s in json.loads((root / 'sample.json').read_text(encoding='utf-8')) if s['scene_token'] in train}
    frames = load_frames_nusc(args.annotations_from, 'all', args.annotations_version, samples=samples)
    print(f"{len(train)} train scenes, {len(frames)} keyframes, {sum(len(f['boxes']) for f in frames)} cuboids")
    cfg = lq.load_cfg()
    cfg['size'], cfg['size_margin'] = calibrate_sizes(frames, args.budget)
    n_fa = sum(1 for f in frames for b in f['boxes'] if lq.size_outliers(b, cfg))
    print(f"size margin {cfg['size_margin']} (scene folds); on train {n_fa / len(frames):.2f} size flags / frame")
    ov = overlap_stats(frames, cfg)
    print(f"overlap flags on train: {sum(ov.values()) / len(frames):.3f} / frame; "
          + ', '.join(f'{k} {v}' for k, v in ov.most_common(6)))
    if not args.dry_run:
        out = {k: v for k, v in cfg.items() if k != 'track'}
        out['track'] = cfg['track']
        out['_note'] = (f"LiDAR thresholds: labeler/calib_lidar.py --split train (nuScenes-mini); class sizes: "
                        f"--annotations-from {args.annotations_version} train split (v2)")
        lq.CFG_PATH.write_text(json.dumps(out, indent=1), encoding='utf-8')
        print(f'wrote {lq.CFG_PATH}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='train', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--budget', type=float, default=0.005, help='false-alarm rate allowed per check on clean cuboids')
    ap.add_argument('--rows', help='reuse the cuboid measurements pickled by an earlier run')
    ap.add_argument('--annotations-from', metavar='ROOT',
                    help='only re-learn the annotation-based thresholds (class sizes, overlap) from the train split of '
                         'this nuScenes (e.g. D:/data/nuscenes-trainval, metadata is enough) and keep the LiDAR ones')
    ap.add_argument('--annotations-version', default='v1.0-trainval')
    ap.add_argument('--max-frames', type=int)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if args.annotations_from:
        relearn_annotation_thresholds(args)
        return
    frames = load_frames_nusc(args.nusc_root, args.split)[:args.max_frames]
    print(f'{len(frames)} {args.split} frames')
    import pickle
    if args.rows:
        rows = pickle.loads(Path(args.rows).read_bytes())
    else:
        rows = collect(frames)
        (ROOT / 'cache' / f'calib_rows_{args.split}.pkl').write_bytes(pickle.dumps(rows))
    cfg = calibrate(rows, args.budget)
    cfg['size'], cfg['size_margin'] = calibrate_sizes(frames, args.budget)
    print(f"size margin (leave-one-scene-out): {cfg['size_margin']}")
    report(rows, cfg, f'{args.split}, budget {args.budget}: ')
    report([r for r in rows if r['clean_in'] >= OBSERVABLE], cfg, f'only cuboids with >= {OBSERVABLE} LiDAR points: ')
    if not args.dry_run:
        out = {k: v for k, v in cfg.items()}
        out['_note'] = f'labeler/calib_lidar.py --split {args.split} --budget {args.budget}'
        lq.CFG_PATH.write_text(json.dumps(out, indent=1), encoding='utf-8')
        print(f'\nwrote {lq.CFG_PATH}')


if __name__ == '__main__':
    main()
