"""Grade labelled cuboids against nuScenes GT with the M44 pilot rules (scripts/pilot_score.py and
scripts/pilot_label_score.py of the M44 repo), so app runs and CVAT runs are comparable.

Targets = GT cars and pedestrians at least 60 % visible (visibility >= 3) within 30 m of the ego car.
Each labelled car / pedestrian cuboid is
  * correct – same object within tolerance (center 0.7 m, every side 25 %, heading 20 deg mod 180,
              heading ignored for pedestrians),
  * rough   – right class within 2 m of an object but not within tolerance,
  * wrong   – no object of that class nearby (ghost box / wrong class).
Matching is one-to-one, closest first, correct before rough.
"""
import math

import numpy as np

CLASSES = ('car', 'pedestrian')
TARGET_RANGE_M, ROUGH_M = 30.0, 2.0
TOL_CENTER_M, TOL_SIZE, TOL_YAW_DEG = 0.7, 0.25, 20.0


def _gravity(b: dict) -> np.ndarray:
    return np.asarray(b['center']) + [0, 0, b['size'][2] / 2]


def same_object(gt: dict, box: dict) -> float | None:
    """Distance if `box` reproduces `gt` within tolerance, else None."""
    if box['cls'] != gt['cls']:
        return None
    dist = float(np.linalg.norm(_gravity(gt) - _gravity(box)))
    if dist > TOL_CENTER_M:
        return None
    if any(abs(b / g - 1) > TOL_SIZE for g, b in zip(gt['size'], box['size']) if g > 0):
        return None
    d_yaw = abs((box['yaw'] - gt['yaw'] + math.pi / 2) % math.pi - math.pi / 2)  # 180 deg flip allowed
    if gt['cls'] not in ('pedestrian', 'traffic_cone') and math.degrees(d_yaw) > TOL_YAW_DEG:
        return None  # heading of round-ish objects is not meaningful
    return dist


def is_target(g: dict) -> bool:
    return g['cls'] in CLASSES and (g.get('visibility') or 0) >= 3 and np.hypot(*g['center'][:2]) <= TARGET_RANGE_M


def grade(gt_boxes: list[dict], boxes: list[dict]) -> tuple[dict, dict]:
    """(status of each labelled box, status of each target object: correct / rough / missed)."""
    gt = [g for g in gt_boxes if g['cls'] in CLASSES]
    targets = {g['box_id'] for g in gt if is_target(g)}
    mine = [b for b in boxes if b['cls'] in CLASSES]

    status, matched_gt = {}, {}
    for level in ('correct', 'rough'):
        pairs = []
        for b in mine:
            if b['box_id'] in status:
                continue
            for g in gt:
                if g['box_id'] in matched_gt:
                    continue
                if level == 'correct':
                    d = same_object(g, b)
                else:
                    d = float(np.linalg.norm(_gravity(g) - _gravity(b))) if g['cls'] == b['cls'] else None
                    d = d if d is not None and d <= ROUGH_M else None
                if d is not None:
                    pairs.append((d, b['box_id'], g['box_id']))
        for d, bid, gid in sorted(pairs):
            if bid not in status and gid not in matched_gt:
                status[bid], matched_gt[gid] = level, level
    for b in mine:
        status.setdefault(b['box_id'], 'wrong')
    return status, {gid: matched_gt.get(gid, 'missed') for gid in targets}


def summary(gt_boxes: list[dict], boxes: list[dict]) -> dict:
    """Counts in the same keys as the M44 pilot result files."""
    status, target_status = grade(gt_boxes, boxes)
    count = lambda d, v: sum(x == v for x in d.values())  # noqa: E731
    return {'targets': len(target_status), 'target_correct': count(target_status, 'correct'),
            'target_rough': count(target_status, 'rough'), 'target_missed': count(target_status, 'missed'),
            'labelled': len(status), 'correct': count(status, 'correct'), 'rough': count(status, 'rough'),
            'wrong': count(status, 'wrong'), 'box_status': status, 'target_status': target_status}
