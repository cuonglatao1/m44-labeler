"""nuScenes frames, LiDAR points and cached YOLO detections, loaded once at startup."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from m44.loader import load_frames_nusc

from .propose import Sweep

MAX_RANGE = 60.0  # m – points farther than this are not sent to the browser


class Dataset:
    def __init__(self, nusc_root: str, version: str, det_dir: Path, splits: tuple[str, ...] = ('val', 'train')):
        self.det_dir = det_dir
        self.frames: list[dict] = []
        for split in splits:  # val first: "val frame N" means the same frame as in the M44 repo
            for k, f in enumerate(load_frames_nusc(nusc_root, split, version)):
                self.frames.append({**f, 'split': split, 'split_index': k})
        self.by_sample = {f['sample']: f for f in self.frames}
        # temporal QC: frame indices of each scene in time order, and the nuScenes instance of every GT cuboid
        scenes = defaultdict(list)
        for i, f in enumerate(self.frames):
            scenes[f['scene']].append(i)
        self.scene_frames = {s: sorted(ix, key=lambda i: self.frames[i]['timestamp']) for s, ix in scenes.items()}
        self.gt_instance = {b['box_id']: b['instance'] for f in self.frames for b in f['boxes']}
        self._sweep: tuple[int, Sweep] | None = None

    def dets(self, sample: str) -> list[dict]:
        p = self.det_dir / f'{sample}.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []

    def has_dets(self, sample: str) -> bool:
        return (self.det_dir / f'{sample}.json').exists()

    def raw_points(self, i: int, ring: bool = False) -> np.ndarray:
        """x, y, z, intensity (+ ring index with ring=True) in the LiDAR frame."""
        pts = np.fromfile(self.frames[i]['lidar_path'], dtype=np.float32).reshape(-1, 5)
        return pts if ring else pts[:, :4]

    def points(self, i: int) -> bytes:
        """LiDAR sweep as float32 x, y, z, intensity (LiDAR frame), cropped to MAX_RANGE."""
        pts = self.raw_points(i)
        keep = np.hypot(pts[:, 0], pts[:, 1]) < MAX_RANGE
        return np.ascontiguousarray(pts[keep]).tobytes()

    def sweep(self, i: int) -> Sweep:
        """Ground model + non-ground points for proposals and the LiDAR QC; the last frame used is kept."""
        if self._sweep is None or self._sweep[0] != i:
            self._sweep = (i, Sweep(self.raw_points(i, ring=True)))
        return self._sweep[1]

    def neighbours(self, i: int, k: int) -> list[int]:
        """Up to k keyframes before and after frame i in the same scene (time order, i itself excluded)."""
        ix = self.scene_frames[self.frames[i]['scene']]
        r = ix.index(i)
        return ix[max(0, r - k):r] + ix[r + 1:r + 1 + k]
