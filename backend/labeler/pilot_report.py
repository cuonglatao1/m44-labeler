"""Pilot comparison table: app runs (with / without assist), CVAT pilot runs and the one-key baseline.

  python -m labeler.pilot_report --cvat-dir D:/m44-consistency-checker/out/pilot

App runs come from cache/labels.db (pilot_runs). CVAT runs are the result files of the M44 pilot part 2
(scripts/pilot_label_score.py: <name>_label_truoc.json / <name>_label_sau.json), graded with the same rules
(labeler/score.py). The baseline is Shift+G on the empty frame without any manual edit (eval_assist.py).
Writes cache/pilot_report.csv as well.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

from m44.loader import load_frames_nusc
from m44.match import DEFAULT_CFG, load_cfg

from .eval_assist import assist
from .score import summary
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
COLS = ['who', 'tool', 'minutes', 'targets', 'target_correct', 'target_rough', 'target_missed', 'wrong']


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # Vietnamese headers on a cp1252 Windows console
    ap = argparse.ArgumentParser()
    ap.add_argument('--cvat-dir', help='out/pilot of the M44 repo')
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    ap.add_argument('--baseline-val', type=int, nargs='*', default=[25, 60],
                    help='val frames that always get the one-key baseline (CVAT frame, app frame)')
    args = ap.parse_args()

    rows = []
    for r in Store(ROOT / 'cache' / 'labels.db').pilot_runs():
        rows.append({'who': r['name'], 'tool': 'app + trợ giúp' if r['assist'] else 'app, không trợ giúp',
                     'sample': r['sample'], **{k: r.get(k) for k in COLS if k in r}})
    if args.cvat_dir:
        cvat = {}
        for p in sorted(Path(args.cvat_dir).glob('*_label_*.json')):
            r = json.loads(p.read_text(encoding='utf-8'))
            cvat.setdefault(r['name'], {})[r['stage']] = r
            stage = 'CVAT (trước M44 Check)' if r['stage'] == 'truoc' else 'CVAT + M44 Check (sau sửa)'
            rows.append({'who': r['name'], 'tool': stage, 'sample': None, **{k: r.get(k) for k in COLS if k in r}})
        # comparable with one app run: labelling + fixing time, quality after fixing
        for name, st in cvat.items():
            if {'truoc', 'sau'} <= set(st):
                rows.append({'who': name, 'tool': 'CVAT + M44 Check (tổng)', 'sample': None,
                             **{k: st['sau'].get(k) for k in COLS if k in st['sau']},
                             'minutes': round(st['truoc']['minutes'] + st['sau']['minutes'], 1)})

    val = load_frames_nusc(args.nusc_root, 'val')
    name = {f['sample']: f'val {i}' for i, f in enumerate(val)}
    samples = {r['sample'] for r in rows if r['sample']} | {val[i]['sample'] for i in args.baseline_val}
    cfg = {**DEFAULT_CFG, **load_cfg(str(ROOT / 'configs' / 'tuned.json'))}
    for f in load_frames_nusc(args.nusc_root, 'all', samples=samples):
        p = ROOT / 'cache' / 'dets' / f"{f['sample']}.json"
        dets = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        s = summary(f['boxes'], assist(f, dets, cfg))
        rows.append({'who': '(máy)', 'tool': f"chỉ Shift+G, không chỉnh – {name.get(f['sample'], f['sample'][:8])}",
                     'sample': f['sample'], 'minutes': 0, **{k: s[k] for k in COLS if k in s}})
    for r in rows:  # which frame each app run was on
        if r['sample'] and r['who'] != '(máy)':
            r['tool'] += f" – {name.get(r['sample'], r['sample'][:8])}"

    print('| ' + ' | '.join(['người', 'công cụ', 'phút', 'mục tiêu', 'đúng', 'lệch', 'sót', 'sai/thừa']) + ' |')
    print('|' + '---|' * len(COLS))
    for r in sorted(rows, key=lambda r: (r['tool'], r['who'])):
        print('| ' + ' | '.join('' if r.get(k) is None else str(r[k]) for k in COLS) + ' |')
    out = ROOT / 'cache' / 'pilot_report.csv'
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS + ['sample'], extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f'\n{out}')


if __name__ == '__main__':
    main()
