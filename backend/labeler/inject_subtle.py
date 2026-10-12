"""Small, human-like labelling errors (the M44 errors – 1-2.5 m shifts, x0.6 / x1.6 sizes, 90° turns, car <-> pedestrian –
are large on purpose). Same output as m44.inject so every evaluation can use either set (--errors subtle).

  SHIFT    0.3-0.6 m in a random direction
  YAW      10-20° (vehicles and two-wheelers: a person has no clear heading)
  FLIP     180° – front and back swapped (elongated cuboids only)
  LENGTH   length x0.75 or x1.3 (one dimension, the others kept)
  HEIGHT   bottom raised or lowered by 0.25 m
  CONFUSE  a class easy to confuse: car <-> truck, bus -> truck, trailer -> truck, bicycle <-> motorcycle,
           construction_vehicle -> truck

Note on the pilot tolerance (labeler/score.same_object: center 0.7 m, sides 25 %, heading 20° mod 180°): some of these
errors are inside it (SHIFT, YAW, FLIP, HEIGHT) – they are still errors a reviewer wants to see.
"""
import copy
import math
import random

TYPES = ['SHIFT', 'YAW', 'FLIP', 'LENGTH', 'HEIGHT', 'CONFUSE']
CONFUSE = {'car': 'truck', 'truck': 'car', 'bus': 'truck', 'trailer': 'truck', 'bicycle': 'motorcycle',
           'motorcycle': 'bicycle', 'construction_vehicle': 'truck'}
HEADED = {'car', 'truck', 'bus', 'trailer', 'construction_vehicle', 'bicycle', 'motorcycle'}


def _apply(box: dict, etype: str, rng: random.Random) -> str | None:
    """Corrupt the box in place; None when this error does not apply to it."""
    if etype == 'SHIFT':
        d, a = rng.uniform(0.3, 0.6), rng.uniform(0, 2 * math.pi)
        box['center'][0] += d * math.cos(a)
        box['center'][1] += d * math.sin(a)
        return f'shift {d:.2f} m'
    if etype == 'YAW':
        if box['cls'] not in HEADED:
            return None
        deg = rng.uniform(10, 20) * rng.choice([-1, 1])
        box['yaw'] += math.radians(deg)
        return f'yaw {deg:+.0f} deg'
    if etype == 'FLIP':
        if box['size'][0] / box['size'][1] < 1.5:
            return None
        box['yaw'] += math.pi
        return 'yaw 180 deg'
    if etype == 'LENGTH':
        k = rng.choice([0.75, 1.3])
        box['size'][0] *= k
        return f'length x{k}'
    if etype == 'HEIGHT':
        dz = rng.choice([-0.25, 0.25])
        box['center'][2] += dz
        return f'bottom {dz:+.2f} m'
    if etype == 'CONFUSE':
        if box['cls'] not in CONFUSE:
            return None
        old, box['cls'] = box['cls'], CONFUSE[box['cls']]
        return f'{old} -> {box["cls"]}'
    raise ValueError(etype)


def inject_subtle(frames: list[dict], eligible: set[str], rate: float = 0.3, seed: int = 0):
    """(noisy_frames, injected_errors) like m44.inject: `rate` of the eligible cuboids of every frame, the error types
    taken in turn; an error that does not apply to a cuboid falls back to SHIFT."""
    rng = random.Random(seed)
    noisy = copy.deepcopy(frames)
    injected = []
    for frame in noisy:
        cands = [b for b in frame['boxes'] if b['box_id'] in eligible]
        rng.shuffle(cands)
        n = max(1, round(rate * len(cands))) if cands else 0
        start = rng.randrange(len(TYPES))
        for k, box in enumerate(cands[:n]):
            etype = TYPES[(start + k) % len(TYPES)]
            detail = _apply(box, etype, rng)
            if detail is None:
                etype, detail = 'SHIFT', _apply(box, 'SHIFT', rng)
            injected.append({'sample': frame['sample'], 'box_id': box['box_id'], 'type': etype, 'detail': detail})
    return noisy, injected
