"""How much manual work does the tool save when a whole scene is labelled from scratch? (simulated annotator)

There is no human pilot, so an annotator is simulated, frame after frame of each scene, with the app's own tools:

  first frame   Shift+G (a cuboid for every YOLO box without one, labeler/propose.py)
  next frames   Ctrl+B (copy the previous frame's cuboids: ego motion + object velocity, labeler/propagate.py),
                then Shift+G for the objects that appeared
  every frame   whatever the tools did not get right is fixed by hand; the annotator then moves on with a correct
                frame (= GT), as a careful annotator would

Every cuboid the tools place is graded against GT with the pilot rule (labeler/score.same_object: center 0.7 m, sides
25 %, heading 20°):

  correct   nothing to do                        rough   right object within 2 m: one adjustment
  wrong     no such object nearby: one delete    gone    copy of an object that left: one delete
  missed    GT object no tool placed: drawn by hand (what labelling everything by hand costs for every object)

  python -m labeler.eval_effort --split val
"""
import argparse
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from m44.geometry import project_frame
from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, check, load_cfg

from .propagate import propagate
from .propose import Sweep, propose_missing
from .score import same_object

ROOT = Path(__file__).resolve().parents[2]
TARGET = ('car', 'pedestrian')  # the pilot's classes; every class is reported too


def grade(placed: list[dict], gt: list[dict]) -> tuple[Counter, set]:
    """Grade tool-placed cuboids against GT. Copies (with an object id) are matched by id, proposals greedily to the
    nearest unmatched GT object of the same class within 2 m. Returns (counts per outcome and class key, matched GT ids)."""
    c = Counter()
    used = set()
    by_inst = {g['instance']: g for g in gt}
    rest = []
    for b in placed:
        g = by_inst.get(b.get('instance')) if b.get('instance') else None
        if b.get('instance') and g is None:
            c[('gone', b['cls'])] += 1
            continue
        if g is None:
            rest.append(b)
            continue
        used.add(g['box_id'])
        c[('correct' if same_object(g, b) is not None else 'rough', g['cls'])] += 1
    for b in rest:
        cands = sorted((math.dist(g['center'][:2], b['center'][:2]), g['box_id']) for g in gt
                       if g['cls'] == b['cls'] and g['box_id'] not in used)
        if cands and cands[0][0] <= 2.0:
            g = next(x for x in gt if x['box_id'] == cands[0][1])
            used.add(g['box_id'])
            c[('correct' if same_object(g, b) is not None else 'rough', g['cls'])] += 1
        else:
            c[('wrong', b['cls'])] += 1
    for g in gt:
        if g['box_id'] not in used:
            c[('missed', g['cls'])] += 1
    return c, used


def shift_g(frame: dict, boxes: list[dict], dets: list[dict], sweep: Sweep, cfg: dict) -> list[dict]:
    flags, _ = check(project_frame({**frame, 'boxes': boxes}), dets, cfg)
    return [{**p, 'box_id': f'p{k}'} for k, p in enumerate(propose_missing(sweep, frame['cams'], flags, boxes))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='val', choices=['train', 'val'])
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--json', help='also write the numbers here')
    ap.add_argument('--shift-g', choices=['every', 'first', 'never'], default='every',
                    help='press Shift+G on every frame (default), on the first frame of a scene only, or never')
    args = ap.parse_args()

    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    frames = load_frames_nusc(args.nusc_root, args.split)
    scenes = defaultdict(list)
    for f in frames:
        scenes[f['scene']].append(f)

    tot = Counter()                   # (outcome, cls) over the whole run
    by_tool = defaultdict(Counter)    # tool -> outcome counts (all classes)
    per_frame = []
    for fs in scenes.values():
        fs.sort(key=lambda f: f['timestamp'])
        for k, f in enumerate(fs):
            p = ROOT / 'cache' / 'dets' / f"{f['sample']}.json"
            dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
            sweep = Sweep(np.fromfile(f['lidar_path'], dtype=np.float32).reshape(-1, 5))
            if k == 0:
                copies = []
            else:
                older = (fs[k - 2], fs[k - 2]['boxes']) if k >= 2 else None
                copies, _ = propagate(f, (fs[k - 1], fs[k - 1]['boxes']), older, [], sweep)
            use_g = args.shift_g == 'every' or (args.shift_g == 'first' and k == 0)
            props = shift_g(f, copies, dets, sweep, cfg) if use_g else []
            c, _ = grade(copies + props, f['boxes'])
            tot.update(c)
            # attribute outcomes to the tool that placed the cuboid
            cc_copy, used = grade(copies, f['boxes'])
            for (o, _), v in cc_copy.items():
                if o != 'missed':
                    by_tool['Ctrl+B'][o] += v
            cc_prop, _ = grade(props, [g for g in f['boxes'] if g['box_id'] not in used])
            for (o, _), v in cc_prop.items():
                if o != 'missed':
                    by_tool['Shift+G'][o] += v
            per_frame.append({'first': k == 0, 'objects': len(f['boxes']), **{o: sum(v for (oo, _), v in c.items() if oo == o)
                                                                                for o in ('correct', 'rough', 'wrong', 'gone', 'missed')}})

    def summary(cls_filter):
        s = Counter()
        for (o, cls), v in tot.items():
            if cls_filter is None or cls in cls_filter:
                s[o] += v
        return s

    print(f"{len(scenes)} {args.split} scenes, {len(per_frame)} keyframes labelled from scratch, frame after frame; "
          f"Shift+G: {args.shift_g}\n")
    print(f"{'':<26}{'objects':>9}{'correct':>9}{'rough':>8}{'missed':>8}{'wrong':>7}{'gone':>6}"
          f"{'hand work':>11}{'vs by hand':>12}")
    for name, flt in (('car + pedestrian', TARGET), ('every class', None)):
        s = summary(flt)
        n = s['correct'] + s['rough'] + s['missed']
        work = s['rough'] + s['missed'] + s['wrong'] + s['gone']  # one action each (adjust / draw / delete)
        print(f"{name:<26}{n:>9}{s['correct'] / n:>9.0%}{s['rough'] / n:>8.0%}{s['missed'] / n:>8.0%}"
              f"{s['wrong']:>7}{s['gone']:>6}{work:>11}{1 - work / n:>12.0%}")
    first = [r for r in per_frame if r['first']]
    later = [r for r in per_frame if not r['first']]
    for name, rows in (('first frame of a scene', first), ('later frames', later)):
        n = sum(r['objects'] for r in rows)
        print(f"{name:<26}{n:>9}{sum(r['correct'] for r in rows) / n:>9.0%}{sum(r['rough'] for r in rows) / n:>8.0%}"
              f"{sum(r['missed'] for r in rows) / n:>8.0%}{sum(r['wrong'] for r in rows):>7}{sum(r['gone'] for r in rows):>6}")
    print('\nby tool (cuboids it placed): ' + '; '.join(
        f"{t}: {sum(c.values())} placed, {c['correct'] / max(sum(c.values()), 1):.0%} correct, "
        f"{c['rough'] / max(sum(c.values()), 1):.0%} rough, {(c['wrong'] + c['gone']) / max(sum(c.values()), 1):.0%} to delete"
        for t, c in by_tool.items()))
    print('"hand work" = adjust + draw + delete actions; "vs by hand" = share of the actions saved compared with drawing '
          'every object by hand (one action per object)')
    if args.json:
        Path(args.json).write_text(json.dumps({'total': {f'{o}/{c}': v for (o, c), v in tot.items()},
                                               'by_tool': {t: dict(c) for t, c in by_tool.items()},
                                               'per_frame': per_frame}, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
