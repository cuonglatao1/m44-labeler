"""Score flags against injected errors (recall) and measure reprojection error on clean GT."""
from collections import Counter, defaultdict

import numpy as np

from .geometry import iou


def evaluate(flags: list[dict], injected: list[dict], clean_proj: list[dict]) -> dict:
    flagged_boxes = {(f['sample'], f['box_id']) for f in flags if f['box_id']}
    clean_by_box = defaultdict(list)
    for p in clean_proj:
        clean_by_box[(p['sample'], p['box_id'])].append(p)

    caught, explained = [], set()
    for e in injected:
        key = (e['sample'], e['box_id'])
        if e['type'] == 'DELETE':
            # caught if a MISSING_3D flag sits where the deleted cuboid used to project
            hits = [f['flag_id'] for f in flags if f['type'] == 'MISSING_3D' and f['sample'] == e['sample']
                    and any(p['cam'] == f['cam'] and iou(p['bbox'], f['det_bbox']) >= 0.3
                            for p in clean_by_box[key])]
            explained.update(hits)
            caught.append(bool(hits))
        else:
            hits = [f['flag_id'] for f in flags if (f['sample'], f['box_id']) == key]
            explained.update(hits)
            caught.append(key in flagged_boxes)

    by_type = defaultdict(lambda: [0, 0])
    for e, c in zip(injected, caught):
        by_type[e['type']][0] += c
        by_type[e['type']][1] += 1
    unexplained = [f for f in flags if f['flag_id'] not in explained]
    return {
        'injected': len(injected),
        'caught': int(sum(caught)),
        'recall': round(sum(caught) / len(injected), 3) if injected else None,
        'recall_by_type': {t: {'caught': c, 'total': n, 'recall': round(c / n, 3)} for t, (c, n) in sorted(by_type.items())},
        'flags_total': len(flags),
        'flags_unexplained': len(unexplained),
        'flags_unexplained_by_type': dict(Counter(f['type'] for f in unexplained)),
        '_caught_per_error': caught,
    }


def reprojection_stats(matches: list[dict]) -> dict:
    """On clean GT: how well do projected cuboids line up with detections?"""
    if not matches:
        return {}
    ious = np.array([m['iou'] for m in matches])
    centers = np.array([
        np.hypot((m['p_bbox'][0] + m['p_bbox'][2] - m['d_bbox'][0] - m['d_bbox'][2]) / 2,
                 (m['p_bbox'][1] + m['p_bbox'][3] - m['d_bbox'][1] - m['d_bbox'][3]) / 2)
        for m in matches])
    return {
        'pairs': len(matches),
        'iou_mean': round(float(ious.mean()), 3),
        'iou_median': round(float(np.median(ious)), 3),
        'center_err_px_median': round(float(np.median(centers)), 1),
        'center_err_px_p90': round(float(np.percentile(centers, 90)), 1),
    }
