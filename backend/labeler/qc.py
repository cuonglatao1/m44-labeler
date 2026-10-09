"""How sure a flag is: the camera, LiDAR and temporal checks are independent evidence, so a cuboid flagged by two or
more of them is almost always wrong, while a flag from one source alone (a dark car the laser passes through, a loose
YOLO box) needs a look first. Flags are sorted sure-first so N / P and the list start with them.

  certainty = 'high'    the cuboid is flagged by >= 2 sources
              'review'  one source only (MISSING_3D, which has no cuboid, is always 'review')
"""
from collections import defaultdict


def rank_flags(flags: list[dict]) -> list[dict]:
    """Adds `sources` (every source flagging that cuboid) and `certainty`, sorts sure-first, renumbers flag_id."""
    by_box = defaultdict(set)
    for f in flags:
        if f.get('box_id'):
            by_box[f['box_id']].add(f.get('source', 'camera'))
    for f in flags:
        srcs = by_box[f['box_id']] if f.get('box_id') else {f.get('source', 'camera')}
        f['sources'] = sorted(srcs)
        f['certainty'] = 'high' if len(srcs) >= 2 else 'review'
    flags = sorted(flags, key=lambda f: f['certainty'] != 'high')  # stable: keeps camera / LiDAR / temporal order
    for k, f in enumerate(flags):
        f['flag_id'] = f'F{k:04d}'
    return flags
