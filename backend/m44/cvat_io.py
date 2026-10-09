"""CVAT 3D integration: create point-cloud tasks from nuScenes frames, read cuboids back, write QC flags.

CVAT 3D has no Issues / review mode (the Issues tab is 2D-only), so flags are written as a `qc` attribute
on each cuboid; reviewers filter on it in the 3D workspace. Frames are named `<index>_<sample token>` so the
calibration and camera images of each CVAT frame can be found again in nuScenes.

CVAT cuboid points = [x, y, z (gravity center), rx, ry, rz, sx, sy, sz, 0 x 7] in the point-cloud frame;
our boxes are LiDAR-frame bottom-centered with yaw = rz, size = (sx, sy, sz).
"""
import os
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np

CLASSES = ['car', 'truck', 'bus', 'trailer', 'construction_vehicle', 'pedestrian', 'motorcycle', 'bicycle',
           'traffic_cone', 'barrier']
# label names people use in their own CVAT tasks -> checker class (matched case-insensitively)
LABEL_ALIASES = {
    'person': 'pedestrian', 'people': 'pedestrian', 'human': 'pedestrian', 'nguoi': 'pedestrian',
    'vehicle': 'car', 'van': 'car', 'suv': 'car', 'xe_con': 'car', 'oto': 'car',
    'motorbike': 'motorcycle', 'scooter': 'motorcycle', 'xe_may': 'motorcycle',
    'bike': 'bicycle', 'cyclist': 'bicycle', 'xe_dap': 'bicycle',
    'lorry': 'truck', 'xe_tai': 'truck', 'xe_buyt': 'bus', 'cone': 'traffic_cone', 'trafficcone': 'traffic_cone',
}
QC_OK = 'OK'
QC_VALUES = [QC_OK, 'LOW_IOU', 'SIZE_MISMATCH', 'CLASS_MISMATCH', 'NO_2D_MATCH']
VISIBILITY_VALUES = ['4', '3', '2', '1']  # nuScenes levels, 4 = 80–100 % visible (default for new boxes)


# ---------- connection ----------

def load_env(path: str | Path = '.cvat.env') -> None:
    """Read KEY=VALUE lines into os.environ (without overriding variables already set)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def connect():
    from cvat_sdk import make_client

    url = os.environ.get('CVAT_URL', 'http://localhost:8080')
    if os.environ.get('CVAT_ACCESS_TOKEN'):
        return make_client(url, access_token=os.environ['CVAT_ACCESS_TOKEN'])
    user, password = os.environ.get('CVAT_USER'), os.environ.get('CVAT_PASSWORD')
    if not (user and password):
        raise SystemExit('Set CVAT_ACCESS_TOKEN or CVAT_USER + CVAT_PASSWORD (see .cvat.env.example)')
    return make_client(url, credentials=(user, password))


# ---------- nuScenes -> CVAT ----------

def frame_name(i: int, sample: str) -> str:
    return f'{i:04d}_{sample}'


def sample_of(name: str) -> str:
    """Inverse of frame_name for any path CVAT reports, e.g. '0003_<token>/0003_<token>.pcd'."""
    return Path(name).stem.split('_', 1)[1]


def write_pcd(bin_path: str, pcd_path: Path) -> int:
    """nuScenes .pcd.bin (x, y, z, intensity, ring as float32) -> binary PCD with x y z intensity."""
    pts = np.fromfile(bin_path, dtype=np.float32).reshape(-1, 5)[:, :4]
    header = ('VERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n'
              f'WIDTH {len(pts)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(pts)}\nDATA binary\n')
    with open(pcd_path, 'wb') as f:
        f.write(header.encode('ascii'))
        f.write(np.ascontiguousarray(pts).tobytes())
    return len(pts)


def build_task_zip(frames: list[dict], work_dir: str | Path) -> Path:
    """CVAT 'Custom 2' 3D layout: <name>/<name>.pcd + the 6 camera images as related images."""
    work = Path(work_dir)
    data = work / 'data'
    if data.exists():
        shutil.rmtree(data)
    for i, f in enumerate(frames):
        name = frame_name(i, f['sample'])
        d = data / name
        d.mkdir(parents=True)
        write_pcd(f['lidar_path'], d / f'{name}.pcd')
        for cam, c in f['cams'].items():
            shutil.copy(c['img_path'], d / f'{cam}.jpg')
    zip_path = work / 'task_data.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as z:
        for p in sorted(data.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(data).as_posix())
    shutil.rmtree(data)
    return zip_path


def label_specs():
    from cvat_sdk import models

    attrs = [
        models.AttributeRequest(name='visibility', mutable=False, input_type='select',
                                default_value=VISIBILITY_VALUES[0], values=VISIBILITY_VALUES),
        models.AttributeRequest(name='qc', mutable=True, input_type='select',
                                default_value=QC_OK, values=QC_VALUES),
    ]
    return [models.PatchedLabelRequest(name=c, type='cuboid', attributes=attrs) for c in CLASSES]


def create_task(client, name: str, zip_path: Path, project_id: int | None = None):
    from cvat_sdk import models
    from cvat_sdk.core.proxies.tasks import ResourceType

    spec = models.TaskWriteRequest(name=name, project_id=project_id) if project_id else \
        models.TaskWriteRequest(name=name, labels=label_specs())
    return client.tasks.create_from_data(
        spec=spec, resource_type=ResourceType.LOCAL, resources=[str(zip_path)],
        data_params={'image_quality': 80, 'sorting_method': 'lexicographical'},
    )


def _label_maps(task):
    labels = task.get_labels()
    by_name = {lb.name: lb for lb in labels}
    attr_id = {(lb.name, a.name): a.id for lb in labels for a in lb.attributes}
    return by_name, {lb.id: lb.name for lb in labels}, attr_id


def frame_index(task) -> dict[str, int]:
    """sample token -> CVAT frame number, from the frame names CVAT stored."""
    return {sample_of(fr.name): i for i, fr in enumerate(task.get_frames_info())}


def upload_boxes(task, frames: list[dict]) -> int:
    """Put the frames' cuboids into the task (replacing its annotations)."""
    from cvat_sdk import models

    by_name, _, attr_id = _label_maps(task)
    # a project may name labels differently (e.g. "Car"); boxes of classes it lacks are skipped
    label_of = {checker_class(n): lb for n, lb in by_name.items() if checker_class(n)}
    idx = frame_index(task)
    shapes = []
    for f in frames:
        for b in f['boxes']:
            lb = label_of.get(b['cls'])
            if lb is None:
                continue
            l, w, h = b['size']
            x, y, z = b['center']
            attrs = []
            if (lb.name, 'visibility') in attr_id:
                attrs.append(models.AttributeValRequest(spec_id=attr_id[(lb.name, 'visibility')],
                                                        value=str(b.get('visibility') or 4)))
            if (lb.name, 'qc') in attr_id:
                attrs.append(models.AttributeValRequest(spec_id=attr_id[(lb.name, 'qc')], value=QC_OK))
            shapes.append(models.LabeledShapeRequest(
                type='cuboid', frame=idx[f['sample']], label_id=lb.id,
                points=[x, y, z + h / 2, 0.0, 0.0, b['yaw'], l, w, h] + [0.0] * 7, attributes=attrs,
            ))
    task.set_annotations(models.LabeledDataRequest(shapes=shapes))
    return len(shapes)


# ---------- CVAT -> checker ----------

def checker_class(label: str) -> str | None:
    """Map a CVAT label name to a checker class: exact class, alias, or None (not checked)."""
    key = label.strip().lower().replace(' ', '_').replace('-', '_')
    return key if key in CLASSES else LABEL_ALIASES.get(key)


def task_samples(task) -> list[str]:
    """nuScenes sample token of each CVAT frame; explains clearly when the task was not built by the tool."""
    names = [fr.name for fr in task.get_frames_info()]
    bad = [n for n in names if not re.fullmatch(r'\d{4}_[0-9a-f]{32}', Path(n).stem)]
    if bad:
        raise SystemExit(
            f'Task {task.id}: frame "{bad[0]}" không có mã nuScenes trong tên. Tool chỉ kiểm tra được task tạo bằng '
            'scripts/cvat_create_task.py (hoặc từ file zip do script đó tạo), vì cần ảnh camera + calibration '
            'của đúng frame đó.')
    return [sample_of(n) for n in names]


def read_frames(task, base_frames: dict[str, dict]) -> tuple[list[dict], dict]:
    """Current task cuboids as checker frames. Images and calibration come from `base_frames`
    (sample token -> frame from the loader). box_id = 'cvat<shape id>'. Returns (frames, shapes by id).
    Labels are mapped with checker_class(); cuboids of unknown labels are kept out of the check."""
    _, label_name, _ = _label_maps(task)
    attr_name = {a.id: a.name for lb in task.get_labels() for a in lb.attributes}
    samples = task_samples(task)
    missing = [s for s in samples if s not in base_frames]
    if missing:
        raise SystemExit(f'Không tìm thấy frame nuScenes {missing[0]} trong dữ liệu (kiểm tra NUSC_ROOT / data\\nuscenes).')
    shapes = [s for s in task.get_annotations().shapes if str(s.type) == 'cuboid']

    frames = [{**base_frames[s], 'boxes': [], 'cvat_frame': i} for i, s in enumerate(samples)]
    for s in shapes:
        cls = checker_class(label_name[s.label_id])
        if cls is None:
            continue
        x, y, z, _, _, rz, sx, sy, sz = s.points[:9]
        attrs = {attr_name.get(a.spec_id): a.value for a in s.attributes}
        vis = attrs.get('visibility')
        frames[s.frame]['boxes'].append({
            'box_id': f'cvat{s.id}', 'cls': cls,
            'center': [x, y, z - sz / 2], 'size': [sx, sy, sz], 'yaw': rz,
            'visibility': int(vis) if vis and str(vis).isdigit() else None,
        })
    return frames, {f'cvat{s.id}': s for s in shapes}


def write_qc(task, shapes: dict, flags: list[dict]) -> int:
    """Set `qc` on every cuboid: the first flag type found for it, else OK. Returns #cuboids flagged.

    Also sets score = 0 (flagged) / 1 (OK): a filter on a label attribute like `qc != OK` also lets every
    cuboid of *other* labels through (their attribute is undefined), while Score is common to all labels,
    so reviewers can use a single filter rule `Score < 1`."""
    from cvat_sdk import models

    _, label_name, attr_id = _label_maps(task)
    qc_of = {}
    for f in flags:
        if f['box_id'] and f['type'] in QC_VALUES:
            qc_of.setdefault(f['box_id'], f['type'])

    updates = []
    for box_id, s in shapes.items():
        qc_spec = attr_id.get((label_name[s.label_id], 'qc'))  # tasks made in the CVAT UI may lack `qc`
        attrs = [models.AttributeValRequest(spec_id=a.spec_id, value=a.value)
                 for a in s.attributes if a.spec_id != qc_spec]
        if qc_spec is not None:
            attrs.append(models.AttributeValRequest(spec_id=qc_spec, value=qc_of.get(box_id, QC_OK)))
        updates.append(models.LabeledShapeRequest(
            id=s.id, type='cuboid', frame=s.frame, label_id=s.label_id, points=list(s.points),
            occluded=s.occluded, z_order=s.z_order, rotation=s.rotation, group=s.group, source=s.source,
            attributes=attrs, score=0.0 if box_id in qc_of else 1.0,
        ))
    task.update_annotations(models.PatchedLabeledDataRequest(shapes=updates))
    return len(qc_of)


def frame_links(task, flags: list[dict], frames: list[dict]) -> dict[str, str]:
    """flag_id -> URL opening the job at the flag's frame. For a flagged cuboid the URL also carries
    `type=shape&serverID=<id>`, which CVAT turns into a filter showing only that cuboid."""
    url = os.environ.get('CVAT_URL', 'http://localhost:8080').rstrip('/')
    jobs = sorted(task.get_jobs(), key=lambda j: j.start_frame)
    cvat_frame = {f['sample']: f['cvat_frame'] for f in frames}
    links = {}
    for fl in flags:
        n = cvat_frame[fl['sample']]
        job = next(j for j in jobs if j.start_frame <= n <= j.stop_frame)
        link = f'{url}/tasks/{task.id}/jobs/{job.id}?frame={n}'
        if fl['box_id']:  # 'cvat<server id>'
            link += f"&type=shape&serverID={fl['box_id'][4:]}"
        links[fl['flag_id']] = link
    return links
