"""Load frames (6 cameras + calibration + 3D boxes).

Two sources, same output:
  * load_frames_nusc – straight from the nuScenes tables with nuscenes-devkit (default, no mmdet3d needed)
  * load_frames      – from an mmdet3d info .pkl (used for the mmdet3d demo frame)
"""
import argparse
import os
import pickle
from pathlib import Path

import numpy as np

# nuScenes category -> detection class (same mapping as mmdet3d NuScenesDataset); others are ignored
NUSC_CLASSES = {
    'movable_object.barrier': 'barrier', 'vehicle.bicycle': 'bicycle', 'vehicle.bus.bendy': 'bus',
    'vehicle.bus.rigid': 'bus', 'vehicle.car': 'car', 'vehicle.construction': 'construction_vehicle',
    'vehicle.motorcycle': 'motorcycle', 'human.pedestrian.adult': 'pedestrian',
    'human.pedestrian.child': 'pedestrian', 'human.pedestrian.construction_worker': 'pedestrian',
    'human.pedestrian.police_officer': 'pedestrian', 'movable_object.trafficcone': 'traffic_cone',
    'vehicle.trailer': 'trailer', 'vehicle.truck': 'truck',
}
CAMERAS = ['CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_FRONT_LEFT', 'CAM_BACK', 'CAM_BACK_LEFT', 'CAM_BACK_RIGHT']


def _pose(record) -> np.ndarray:
    from pyquaternion import Quaternion

    T = np.eye(4)
    T[:3, :3] = Quaternion(record['rotation']).rotation_matrix
    T[:3, 3] = record['translation']
    return T


def load_frames_nusc(nusc_root: str, split: str = 'val', version: str = 'v1.0-mini',
                     max_frames: int | None = None, samples: set[str] | None = None) -> list[dict]:
    """Frames of one split ('all' = every scene) read directly from the nuScenes tables;
    `samples` keeps only those sample tokens.

    lidar2cam chains LiDAR -> ego (LiDAR time) -> global -> ego (camera time) -> camera, so the ego
    motion between the LiDAR sweep and each camera exposure is compensated (as mmdet3d infos do).
    """
    from nuscenes.nuscenes import NuScenes
    from nuscenes.utils.splits import create_splits_scenes

    nusc = NuScenes(version=version, dataroot=str(nusc_root), verbose=False)
    if split == 'all':
        scenes = {s['name'] for s in nusc.scene}
    else:
        scenes = set(create_splits_scenes()[f'mini_{split}' if version.endswith('mini') else split])

    frames = []
    for sample in nusc.sample:  # same order as mmdet3d infos, so frame N is the same frame in both
        scene = nusc.get('scene', sample['scene_token'])
        if scene['name'] not in scenes or (samples is not None and sample['token'] not in samples):
            continue
        lidar_sd = nusc.get('sample_data', sample['data']['LIDAR_TOP'])
        lidar2global = _pose(nusc.get('ego_pose', lidar_sd['ego_pose_token'])) @ \
            _pose(nusc.get('calibrated_sensor', lidar_sd['calibrated_sensor_token']))

        cams = {}
        for cam in CAMERAS:
            sd = nusc.get('sample_data', sample['data'][cam])
            cs = nusc.get('calibrated_sensor', sd['calibrated_sensor_token'])
            cam2global = _pose(nusc.get('ego_pose', sd['ego_pose_token'])) @ _pose(cs)
            cams[cam] = {
                'img_path': str(nusc.get_sample_data_path(sd['token'])),
                'cam2img': np.asarray(cs['camera_intrinsic'], dtype=float).tolist(),
                'lidar2cam': (np.linalg.inv(cam2global) @ lidar2global).tolist(),
            }

        _, lidar_boxes, _ = nusc.get_sample_data(lidar_sd['token'])  # in LiDAR frame, order of sample['anns']
        boxes = []
        for i, (ann_token, box) in enumerate(zip(sample['anns'], lidar_boxes)):
            ann = nusc.get('sample_annotation', ann_token)
            cls = NUSC_CLASSES.get(ann['category_name'])
            if cls is None:
                continue
            w, l, h = box.wlh
            x, y, z = box.center  # gravity center
            boxes.append({
                'box_id': f"{sample['token'][:8]}_{i:03d}",
                'cls': cls,
                'center': [float(x), float(y), float(z - h / 2)],  # bottom-center
                'size': [float(l), float(w), float(h)],
                'yaw': float(box.orientation.yaw_pitch_roll[0]),
                'num_lidar_pts': int(ann['num_lidar_pts']),
                'visibility': int(ann['visibility_token']),
                'instance': ann['instance_token'],  # labeler addition: temporal QC
            })
        frames.append({'sample': sample['token'], 'night': 'night' in scene['description'].lower(),
                       'lidar_path': str(nusc.get_sample_data_path(lidar_sd['token'])),
                       'lidar2global': lidar2global.tolist(),  # labeler addition: export in the global frame
                       'scene': scene['token'], 'timestamp': int(sample['timestamp']),  # labeler addition: temporal QC
                       'cams': cams, 'boxes': boxes})
        if max_frames and len(frames) >= max_frames:
            break
    return frames


def add_data_args(ap: argparse.ArgumentParser):
    """CLI flags shared by every script: nuScenes folder + split (default) or an mmdet3d info .pkl."""
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'),
                    help='nuScenes folder containing samples/ and v1.0-mini/ (env NUSC_ROOT)')
    ap.add_argument('--split', default='val', choices=['train', 'val', 'all'])
    ap.add_argument('--version', default='v1.0-mini')
    ap.add_argument('--info', help='optional mmdet3d info .pkl instead of the nuScenes tables')
    ap.add_argument('--data-root', help='image root for --info (defaults to --nusc-root)')
    ap.add_argument('--max-frames', type=int)
    ap.add_argument('--start-frame', type=int, default=0, help='skip the first N frames of the split')


def frames_from_args(args) -> list[dict]:
    start = getattr(args, 'start_frame', 0) or 0
    stop = start + args.max_frames if args.max_frames else None
    if args.info:
        frames = load_frames(args.info, args.data_root or args.nusc_root, stop)
    else:
        frames = load_frames_nusc(args.nusc_root, args.split, args.version, stop)
    return frames[start:]


def _resolve(data_root: Path, rel: str, cam: str) -> str:
    for cand in (data_root / rel, data_root / 'samples' / cam / rel, data_root / Path(rel).name):
        if cand.exists():
            return str(cand)
    raise FileNotFoundError(f'image not found for {cam}: {rel} (data_root={data_root})')


def _nusc_meta(data_root: Path, version: str):
    """Per-sample annotation visibility levels (1–4) and night flag from the nuScenes tables, if present."""
    if not (data_root / version).exists():
        return None
    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes(version=version, dataroot=str(data_root), verbose=False)

    def meta(sample_token):
        sample = nusc.get('sample', sample_token)
        scene = nusc.get('scene', sample['scene_token'])
        vis = [int(nusc.get('sample_annotation', a)['visibility_token']) for a in sample['anns']]
        return vis, 'night' in scene['description'].lower()
    return meta


def load_frames(info_path: str, data_root: str, max_frames: int | None = None) -> list[dict]:
    with open(info_path, 'rb') as f:
        info = pickle.load(f)
    id2cls = {v: k for k, v in info['metainfo']['categories'].items()}
    root = Path(data_root)
    meta = _nusc_meta(root, info['metainfo'].get('version', 'v1.0-mini'))

    frames = []
    for s in info['data_list'][:max_frames]:
        # infos keep sample['anns'] order, so instance i <-> annotation i
        vis, night = meta(s['token']) if meta else (None, None)
        if vis is not None and len(vis) != len(s['instances']):
            vis = None
        cams = {
            name: {
                'img_path': _resolve(root, c['img_path'], name),
                'cam2img': np.asarray(c['cam2img'], dtype=float)[:3, :3].tolist(),
                'lidar2cam': np.asarray(c['lidar2cam'], dtype=float).tolist(),
            }
            for name, c in s['images'].items()
        }
        boxes = []
        for i, inst in enumerate(s['instances']):
            label = inst['bbox_label_3d']
            if label < 0:  # ignored category in nuScenes infos
                continue
            # infos store the gravity center; we keep the bottom-center (mmdet3d LiDAR box convention)
            x, y, z, l, w, h, yaw = inst['bbox_3d'][:7]
            boxes.append({
                'box_id': f"{s['token'][:8]}_{i:03d}",
                'cls': id2cls[label],
                'center': [x, y, z - h / 2],  # LiDAR frame, bottom-center
                'size': [l, w, h],
                'yaw': yaw,
                'num_lidar_pts': int(inst.get('num_lidar_pts', -1)),
                'visibility': vis[i] if vis else None,  # nuScenes: 1=0-40%, 2=40-60%, 3=60-80%, 4=80-100%
            })
        frames.append({'sample': s['token'], 'night': night, 'cams': cams, 'boxes': boxes})
    return frames
