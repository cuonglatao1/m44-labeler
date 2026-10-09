"""Inject known labelling errors into clean GT so the checker's recall can be measured."""
import copy
import math
import random

ERROR_TYPES = ['OFFSET', 'SCALE', 'ROTATE', 'CLASS_SWAP', 'DELETE']

# swap to a class the detector cannot confuse with the original
SWAP_TO = {
    'car': 'pedestrian', 'truck': 'pedestrian', 'bus': 'pedestrian', 'trailer': 'pedestrian',
    'construction_vehicle': 'pedestrian', 'pedestrian': 'car', 'bicycle': 'car', 'motorcycle': 'car',
}


def _apply(box: dict, etype: str, rng: random.Random) -> str:
    if etype == 'OFFSET':
        dist, ang = rng.uniform(1.0, 2.5), rng.uniform(0, 2 * math.pi)
        box['center'][0] += dist * math.cos(ang)
        box['center'][1] += dist * math.sin(ang)
        return f'shift {dist:.1f} m'
    if etype == 'SCALE':
        k = rng.choice([0.6, 1.6])
        box['size'] = [s * k for s in box['size']]
        return f'size x{k}'
    if etype == 'ROTATE':
        box['yaw'] += math.pi / 2
        return 'yaw +90 deg'
    if etype == 'CLASS_SWAP':
        old, box['cls'] = box['cls'], SWAP_TO[box['cls']]
        return f'{old} -> {box["cls"]}'
    raise ValueError(etype)


def inject(frames: list[dict], eligible: set[str], rate: float = 0.3, seed: int = 0):
    """Return (noisy_frames, injected_errors). Only boxes in `eligible` are corrupted.

    ROTATE is only applied to elongated boxes (l/w >= 1.5): rotating a pedestrian changes nothing.
    """
    rng = random.Random(seed)
    noisy = copy.deepcopy(frames)
    injected = []
    for frame in noisy:
        cands = [b for b in frame['boxes'] if b['box_id'] in eligible]
        rng.shuffle(cands)
        n = max(1, round(rate * len(cands))) if cands else 0
        start = rng.randrange(len(ERROR_TYPES))
        deleted = set()
        for k, box in enumerate(cands[:n]):
            etype = ERROR_TYPES[(start + k) % len(ERROR_TYPES)]
            if etype == 'ROTATE' and box['size'][0] / box['size'][1] < 1.5:
                etype = 'OFFSET'
            detail = 'removed' if etype == 'DELETE' else _apply(box, etype, rng)
            if etype == 'DELETE':
                deleted.add(box['box_id'])
            injected.append({'sample': frame['sample'], 'box_id': box['box_id'], 'type': etype, 'detail': detail})
        frame['boxes'] = [b for b in frame['boxes'] if b['box_id'] not in deleted]
    return noisy, injected
