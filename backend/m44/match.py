"""Match projected cuboids with 2D detections per camera and raise consistency flags."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from .geometry import IMG_WH, iou, overlap_frac

# nuScenes class -> COCO classes a detector may legitimately call it.
# Classes absent here (barrier, traffic_cone) cannot be verified from COCO detections.
COMPATIBLE = {
    'car': {'car', 'truck'},  # YOLO often calls SUVs/pickups "truck"
    'truck': {'truck', 'car', 'bus'},
    'bus': {'bus', 'truck'},
    'trailer': {'truck'},
    'construction_vehicle': {'truck', 'car'},
    'pedestrian': {'person'},
    'bicycle': {'bicycle', 'person'},
    'motorcycle': {'motorcycle', 'person'},
}

DEFAULT_CFG = {
    'max_depth': 50.0,       # m – farther boxes are too small to judge from pixels
    'min_height_px': 25.0,   # projected box height needed to be checkable
    'min_visible_frac': 0.5,  # share of the projected box inside the image
    'max_occluded': 0.5,     # share covered by nearer projected boxes
    'match_min_iou': 0.1,    # below this a pair is not considered the same object
    'offset_iou': 0.5,       # matched but IoU below this -> misplaced/mis-sized; float or {cls: float}
    'missing_conf': 0.5,     # detection confidence needed to claim a missing cuboid
    'explain_iou': 0.1,      # an unverifiable cuboid of a compatible class this close explains a detection
    'duplicate_iou': 0.5,    # any cuboid this close explains a detection (e.g. car + truck duplicate)
    'min_visibility': 1,     # nuScenes visibility level (1–4) needed to be checkable
    # flags that only mean "the detector saw / did not see something" are weaker evidence:
    'no_match_min_height_px': 25.0,  # NO_2D_MATCH only for cuboids at least this tall
    'missing_min_height_px': 25.0,   # MISSING_3D only for detections at least this tall
    'skip_night': False,     # no NO_2D_MATCH / MISSING_3D on night scenes (detector unreliable)
    # class-incompatible pairs need at least this IoU to be matched at all: a real class error sits on the
    # object (high IoU), a pedestrian in front of a parked car only overlaps the car's detection a little
    'mismatch_min_iou': 0.1,
    # {cls: {"h": [lo, hi], "w": [lo, hi]}} bounds on log(projected/detected) height and width of a
    # matched pair, from clean-GT percentiles (scripts/calibrate.py). Catches wrong size / heading
    # that IoU misses. Empty = disabled.
    'size_bounds': {},
}

BORDER_PX = 2  # width is unreliable when a box is cut by the image border


def _size_outlier(p_bbox, d_bbox, bounds: dict | None) -> bool:
    if not bounds:
        return False
    rh = np.log((p_bbox[3] - p_bbox[1]) / (d_bbox[3] - d_bbox[1]))
    if 'h' in bounds and not bounds['h'][0] <= rh <= bounds['h'][1]:
        return True
    if 'w' in bounds and min(p_bbox[0], d_bbox[0]) > BORDER_PX and max(p_bbox[2], d_bbox[2]) < IMG_WH[0] - BORDER_PX:
        rw = np.log((p_bbox[2] - p_bbox[0]) / (d_bbox[2] - d_bbox[0]))
        return not bounds['w'][0] <= rw <= bounds['w'][1]
    return False


def load_cfg(arg: str | None) -> dict:
    """--cfg value: path to a JSON file or an inline JSON object; overrides DEFAULT_CFG keys."""
    if not arg:
        return {}
    cfg = json.loads(arg if arg.lstrip().startswith('{') else Path(arg).read_text(encoding='utf-8'))
    unknown = set(cfg) - set(DEFAULT_CFG)
    if unknown:
        raise ValueError(f'unknown cfg keys: {sorted(unknown)}')
    return cfg


def _checkable(p: dict, nearer: list[dict], cfg: dict) -> bool:
    if p['cls'] not in COMPATIBLE or p['depth'] > cfg['max_depth']:
        return False
    if p.get('visibility') is not None and p['visibility'] < cfg['min_visibility']:
        return False
    if p['bbox'][3] - p['bbox'][1] < cfg['min_height_px'] or p['visible_frac'] < cfg['min_visible_frac']:
        return False
    occluded = min(1.0, sum(overlap_frac(p['bbox'], q['bbox']) for q in nearer))
    return occluded <= cfg['max_occluded']


def check(proj: list[dict], dets: list[dict], cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Return (flags, matches). Each flag points at a cuboid (box_id) or a detection (det_bbox)."""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    by_cam_p, by_cam_d = defaultdict(list), defaultdict(list)
    for p in proj:
        by_cam_p[(p['sample'], p['cam'])].append(p)
    for d in dets:
        by_cam_d[(d['sample'], d['cam'])].append(d)
    night_of = {p['sample']: p.get('night') for p in proj}
    offset_iou = cfg['offset_iou']

    flags, matches = [], []
    for key in sorted(set(by_cam_p) | set(by_cam_d)):
        sample, cam = key
        P_all, D = by_cam_p[key], by_cam_d[key]
        detector_flags = not (cfg['skip_night'] and night_of.get(sample))
        P = [p for p in P_all
             if _checkable(p, [q for q in P_all if q['depth'] < p['depth'] and q is not p], cfg)]

        # Hungarian on IoU with a small bonus for class-compatible pairs
        matched_p, matched_d = set(), set()
        if P and D:
            score = np.zeros((len(P), len(D)))
            ious = np.zeros_like(score)
            allowed = np.zeros_like(score, dtype=bool)
            for i, p in enumerate(P):
                for j, d in enumerate(D):
                    ious[i, j] = iou(p['bbox'], d['bbox'])
                    compatible = d['cls'] in COMPATIBLE[p['cls']]
                    allowed[i, j] = ious[i, j] >= (cfg['match_min_iou'] if compatible else cfg['mismatch_min_iou'])
                    score[i, j] = ious[i, j] + (0.3 if compatible else 0.0) if allowed[i, j] else -1.0
            rows, cols = linear_sum_assignment(-score)
            for i, j in zip(rows, cols):
                if not allowed[i, j]:
                    continue
                p, d = P[i], D[j]
                matched_p.add(i)
                matched_d.add(j)
                matches.append({'sample': sample, 'cam': cam, 'box_id': p['box_id'], 'iou': float(ious[i, j]),
                                'p_bbox': p['bbox'], 'd_bbox': d['bbox']})
                base = {'sample': sample, 'cam': cam, 'box_id': p['box_id'], 'cls_3d': p['cls'],
                        'cls_2d': d['cls'], 'iou': round(float(ious[i, j]), 3),
                        'p_bbox': p['bbox'], 'det_bbox': d['bbox']}
                if d['cls'] not in COMPATIBLE[p['cls']]:
                    flags.append({**base, 'type': 'CLASS_MISMATCH'})
                elif ious[i, j] < (offset_iou.get(p['cls'], 0.5) if isinstance(offset_iou, dict) else offset_iou):
                    flags.append({**base, 'type': 'LOW_IOU'})
                elif _size_outlier(p['bbox'], d['bbox'], cfg['size_bounds'].get(p['cls'])):
                    flags.append({**base, 'type': 'SIZE_MISMATCH'})

        for i, p in enumerate(P):
            if i not in matched_p and detector_flags \
                    and p['bbox'][3] - p['bbox'][1] >= cfg['no_match_min_height_px']:
                flags.append({'sample': sample, 'cam': cam, 'box_id': p['box_id'], 'cls_3d': p['cls'],
                              'cls_2d': None, 'iou': None, 'p_bbox': p['bbox'], 'det_bbox': None,
                              'type': 'NO_2D_MATCH'})

        for j, d in enumerate(D):
            if j in matched_d or d['score'] < cfg['missing_conf'] or not detector_flags:
                continue
            if d['bbox'][3] - d['bbox'][1] < cfg['missing_min_height_px']:
                continue
            # Is the detection explained by an existing cuboid?
            #  - one we could not verify (far / occluded) of a compatible class: a far pedestrian
            #    or a traffic cone behind a car must not hide the car's missing cuboid;
            #  - any cuboid (matched ones included) overlapping almost fully: duplicate detection.
            #    Matched neighbours with smaller overlap do not count, so crowds don't hide a gap.
            checked_ids = {id(p) for p in P}
            if any(id(p) not in checked_ids and d['cls'] in COMPATIBLE.get(p['cls'], ())
                   and iou(d['bbox'], p['bbox']) >= cfg['explain_iou'] for p in P_all):
                continue
            if max((iou(d['bbox'], p['bbox']) for p in P_all), default=0.0) >= cfg['duplicate_iou']:
                continue
            flags.append({'sample': sample, 'cam': cam, 'box_id': None, 'cls_3d': None, 'cls_2d': d['cls'],
                          'iou': None, 'p_bbox': None, 'det_bbox': d['bbox'], 'score': round(d['score'], 3),
                          'type': 'MISSING_3D'})

    for k, f in enumerate(flags):
        f['flag_id'] = f'F{k:04d}'
    return flags, matches
