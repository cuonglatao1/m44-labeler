"""FastAPI backend: frames, LiDAR points, camera images, cuboid storage and the live M44 check.

  cd backend && python -m uvicorn labeler.main:app --port 8770
"""
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from m44.geometry import project_frame
from m44.match import DEFAULT_CFG, check, load_cfg

from . import assistant, lidar_qc, missing, track
from .propagate import dismissed_types, new_instance, propagate
from .qc import rank_flags
from .dataset import Dataset
from .fix import suggest
from .export import to_nuscenes
from .propose import propose, propose_missing
from .score import summary
from .store import Store, pilot_key

ROOT = Path(__file__).resolve().parents[2]
NUSC_ROOT = os.environ.get('NUSC_ROOT', str(ROOT / 'data' / 'nuscenes'))
CFG = {**DEFAULT_CFG, **load_cfg(os.environ.get('M44_CFG', str(ROOT / 'configs' / 'tuned.json')))}

LQC = lidar_qc.load_cfg()  # LiDAR + temporal QC thresholds (configs/lidar_qc.json)

ds = Dataset(NUSC_ROOT, os.environ.get('NUSC_VERSION', 'v1.0-mini'), ROOT / 'cache' / 'dets')
store = Store(ROOT / 'cache' / 'labels.db')

app = FastAPI(title='M44 Labeler')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173'], allow_methods=['*'],
                   allow_headers=['*'])


class Box(BaseModel):
    box_id: str
    cls: str
    center: list[float]  # LiDAR frame, bottom-center
    size: list[float]    # l, w, h
    yaw: float
    visibility: int | None = None  # nuScenes level 1-4; None for boxes drawn in the app
    num_lidar_pts: int | None = None
    instance: str | None = None  # object id across frames: nuScenes instance token, or obj_<hex> for app cuboids
    source: str | None = None  # None = GT / drawn by hand, 'proposal' = made by /propose, 'propagated' = /propagate
    proposal: dict | None = None  # method, fit_iou, cam of a proposal
    propagated: dict | None = None  # from (sample), moved (m, LiDAR snap), points, motion of a propagated cuboid


class Boxes(BaseModel):
    boxes: list[Box]


class PropagateReq(BaseModel):
    boxes: list[Box]  # the cuboids already in the current frame (not copied twice)
    direction: Literal['prev', 'next'] = 'prev'


class ProposeOne(BaseModel):
    cam: str
    bbox: list[float]
    cls: str  # COCO class of the detection


class SuggestReq(BaseModel):
    flag: dict
    boxes: list[Box]


class ChatReq(BaseModel):
    session_id: str
    frame_index: int
    boxes: list[Box]
    message: str
    selected: str | None = None
    active_flag: dict | None = None


class Event(BaseModel):
    kind: str  # e.g. flag_accept, flag_false_alarm
    data: dict = {}


def _frame(i: int) -> dict:
    if not 0 <= i < len(ds.frames):
        raise HTTPException(404, f'frame {i} out of range (0-{len(ds.frames) - 1})')
    return ds.frames[i]


def _neighbour_boxes(i: int, pilot: str | None, assist: bool) -> list[tuple[dict, list[dict]]]:
    """Cuboids of the keyframes around frame i for the temporal check: the saved labels, else GT. A pilot only ever
    sees their own drafts (never GT)."""
    out = []
    for j in ds.neighbours(i, track.K_FRAMES):
        fj = ds.frames[j]
        saved = store.get_boxes(pilot_key(fj['sample'], pilot, assist))
        if saved is None and pilot:
            continue
        out.append((fj, saved if saved is not None else fj['boxes']))
    return out


def _run_check(i: int, boxes: list[dict], pilot: str | None = None, assist: bool = True) -> dict:
    """Camera check (M44) + LiDAR check + temporal check of the given cuboids.

    Every flag gets `source` (camera / lidar / track) and a camera to look at (LiDAR / temporal flags: the camera where
    the cuboid projects biggest, None if none). qc[box_id] = status per source (ok / flagged / none) and the combined
    QC level: flagged, high (verified by 2+ sources), medium (1 source), none (no source could verify it).
    """
    frame = ds.frames[i]
    proj = project_frame({**frame, 'boxes': boxes})
    flags, matches = check(proj, ds.dets(frame['sample']), CFG)
    for f in flags:
        f['source'] = 'camera'
    lflags, linfo = lidar_qc.lidar_check(boxes, ds.sweep(i), LQC)
    neighbours = _neighbour_boxes(i, pilot, assist)
    tflags, tinfo = track.track_check(frame, boxes, neighbours, ds.gt_instance, LQC['track'])
    best = {}
    for p in proj:
        a = (p['bbox'][2] - p['bbox'][0]) * (p['bbox'][3] - p['bbox'][1])
        if a > best.get(p['box_id'], (0, None, None))[0]:
            best[p['box_id']] = (a, p['cam'], p['bbox'])
    for src, fl in (('lidar', lflags), ('track', tflags)):
        for f in fl:
            _, cam, bbox = best.get(f['box_id'], (0, None, None))
            flags.append({'sample': frame['sample'], 'cam': cam, 'cls_2d': None, 'iou': None, 'p_bbox': bbox,
                          'det_bbox': None, 'source': src, **f})
    # objects with no cuboid at all, found without the camera (labeler/missing.py)
    miss = missing.track_missing(frame, boxes, neighbours, ds.gt_instance, LQC['track'])
    miss, unboxed = missing.corroborate(miss, frame, ds.sweep(i), flags, LQC)
    for src, fl in (('track', miss), ('lidar', unboxed)):
        for f in fl:
            cam, bbox = missing.best_camera(f['detail']['box'], frame)
            flags.append({'sample': frame['sample'], 'cam': cam, 'cls_2d': None, 'iou': None, 'p_bbox': bbox,
                          'det_bbox': None, 'source': src, **f})
    flags = rank_flags(flags)  # certainty (sources agreeing on the cuboid), sure-first, renumbered

    matched = {m['box_id'] for m in matches}
    flagged = {(f['source'], f['box_id']) for f in flags if f.get('box_id')}
    qc = {}
    for b in boxes:
        bid = b['box_id']
        st = {'camera': 'flagged' if ('camera', bid) in flagged else 'ok' if bid in matched else 'none',
              'lidar': 'flagged' if ('lidar', bid) in flagged else 'ok' if linfo[bid]['checked'] else 'none',
              'track': 'flagged' if ('track', bid) in flagged else 'ok' if tinfo[bid]['checked'] else 'none'}
        n_ok = sum(v == 'ok' for v in st.values())
        level = 'flagged' if 'flagged' in st.values() else 'high' if n_ok >= 2 else 'medium' if n_ok else 'none'
        li, ti = linfo[bid], tinfo[bid]
        qc[bid] = {**st, 'level': level, 'rays': li['rays'], 'pass_xy': li['pass_xy'], 'n_inside': li['n_inside'],
                   'n_spill': li['n_spill'], 'ground_gap': li['ground_gap'], 'n_obs': ti.get('n_obs', 0)}
    n = max(len(boxes), 1)
    coverage = {src: round(sum(q[src] != 'none' for q in qc.values()) / n, 3) for src in ('camera', 'lidar', 'track')}
    coverage['any'] = round(sum(q['level'] != 'none' for q in qc.values()) / n, 3)
    return {'proj': proj, 'flags': flags, 'matches': matches, 'qc': qc, 'coverage': coverage}


@app.get('/api/frames')
def list_frames():
    labelled = store.labelled()
    return [{'index': i, 'sample': f['sample'], 'split': f['split'], 'split_index': f['split_index'],
             'night': f['night'], 'n_gt': len(f['boxes']), 'labelled': f['sample'] in labelled,
             'has_dets': ds.has_dets(f['sample'])} for i, f in enumerate(ds.frames)]


@app.get('/api/frames/{i}')
def get_frame(i: int, init: Literal['gt', 'empty'] = 'gt', source: Literal['auto', 'gt', 'empty'] = 'auto',
              pilot: str | None = None, assist: bool = True):
    """Frame calibration, cuboids, detections and the check result.

    source=auto: the saved cuboids, else GT or nothing depending on `init`; source=gt/empty: reset to that.
    pilot=<name>: that person's pilot draft, always starting empty (GT is never sent), plus the pilot clock.
    """
    f = _frame(i)
    key = pilot_key(f['sample'], pilot, assist)
    saved = store.get_boxes(key)
    if pilot:
        boxes = saved or []
    elif source == 'auto' and saved is not None:
        boxes = saved
    else:
        boxes = f['boxes'] if (source if source != 'auto' else init) == 'gt' else []
    boxes = _with_instance(boxes)
    extra = {'pilot': {'name': pilot, 'assist': assist, 'started': store.pilot_start(key),
                       'run': store.pilot_run(key)}} if pilot else {}
    return {
        **extra,
        'index': i, 'sample': f['sample'], 'split': f['split'], 'split_index': f['split_index'],
        'night': f['night'], 'saved': saved is not None,
        'cams': {name: {'cam2img': c['cam2img'], 'lidar2cam': c['lidar2cam']} for name, c in f['cams'].items()},
        'boxes': boxes,
        'dets': ds.dets(f['sample']),
        'feedback': store.feedback(key),
        **_run_check(i, boxes, pilot, assist),
    }


@app.get('/api/frames/{i}/points')
def get_points(i: int):
    _frame(i)
    return Response(ds.points(i), media_type='application/octet-stream')


@app.get('/api/frames/{i}/image/{cam}')
def get_image(i: int, cam: str):
    f = _frame(i)
    if cam not in f['cams']:
        raise HTTPException(404, f'unknown camera {cam}')
    return FileResponse(f['cams'][cam]['img_path'], media_type='image/jpeg')


@app.post('/api/frames/{i}/check')
def post_check(i: int, body: Boxes, pilot: str | None = None, assist: bool = True):
    """Live check of unsaved cuboids (called while the annotator edits)."""
    _frame(i)
    return _run_check(i, [b.model_dump() for b in body.boxes], pilot, assist)


@app.put('/api/frames/{i}/boxes')
def put_boxes(i: int, body: Boxes, pilot: str | None = None, assist: bool = True):
    f = _frame(i)
    boxes = [b.model_dump() for b in body.boxes]
    store.put_boxes(pilot_key(f['sample'], pilot, assist), boxes)
    return _run_check(i, boxes, pilot, assist)


@app.post('/api/frames/{i}/events')
def post_event(i: int, body: Event, pilot: str | None = None, assist: bool = True):
    store.log(pilot_key(_frame(i)['sample'], pilot, assist), body.kind, body.data)
    return {'ok': True}


@app.post('/api/frames/{i}/pilot_submit')
def pilot_submit(i: int, body: Boxes, pilot: str, assist: bool = True):
    """Hand in a pilot: store the cuboids, grade them with the M44 pilot rules, record the time."""
    f = _frame(i)
    key = pilot_key(f['sample'], pilot, assist)
    boxes = [b.model_dump() for b in body.boxes]
    store.put_boxes(key, boxes)
    score = summary(f['boxes'], boxes)
    score.pop('target_status')  # GT ids: not sent to the browser
    return store.pilot_submit(key, pilot, f['sample'], assist, score, boxes)


@app.get('/api/pilot/results')
def pilot_results():
    return store.pilot_runs()


_n_new = 0


def _as_box(sample: str, p: dict, cam: str) -> dict:
    """A proposal as an app cuboid with a fresh id."""
    global _n_new
    _n_new += 1
    return {'box_id': f'prop_{sample[:6]}_{_n_new:04d}', 'cls': p['cls'], 'center': p['center'],
            'size': p['size'], 'yaw': p['yaw'], 'visibility': None, 'num_lidar_pts': p['n_points'],
            'instance': new_instance(),
            'source': 'proposal', 'proposal': {'method': p['method'], 'fit_iou': p['fit_iou'], 'cam': cam}}


@app.post('/api/frames/{i}/propose')
def post_propose(i: int, body: ProposeOne, pilot: str | None = None, assist: bool = True):
    """Cuboid proposed from one camera detection (2D → 3D)."""
    f = _frame(i)
    if body.cam not in f['cams']:
        raise HTTPException(404, f'unknown camera {body.cam}')
    p = propose(ds.sweep(i), f['cams'][body.cam], body.bbox, body.cls)
    if p is None:
        raise HTTPException(422, 'no LiDAR points and no ground hit for this box')
    box = _as_box(f['sample'], p, body.cam)
    store.log(pilot_key(f['sample'], pilot, assist), 'propose', {'box': box, 'bbox': body.bbox})
    return box


def _with_instance(boxes: list[dict]) -> list[dict]:
    """Every cuboid carries an object id: GT ones (and cuboids edited from them) their nuScenes instance token, older
    saved cuboids without one get a new id here (kept from the next save on)."""
    return [b if b.get('instance') else {**b, 'instance': ds.gt_instance.get(b['box_id']) or new_instance()} for b in boxes]


def _labels_of(j: int, pilot: str | None, assist: bool) -> list[dict] | None:
    """Cuboids of frame j to copy from: the saved labels, else GT (never GT for a pilot)."""
    fj = ds.frames[j]
    saved = store.get_boxes(pilot_key(fj['sample'], pilot, assist))
    if saved is not None:
        return saved
    return None if pilot else fj['boxes']


@app.post('/api/frames/{i}/propagate')
def post_propagate(i: int, body: PropagateReq, pilot: str | None = None, assist: bool = True):
    """Copy the cuboids of the previous (or next) keyframe of the scene into frame i: ego motion compensated, moving
    objects pushed forward with their velocity, snapped to the LiDAR points, object ids kept (labeler/propagate.py)."""
    f = _frame(i)
    ix = ds.scene_frames[f['scene']]
    r = ix.index(i)
    step = -1 if body.direction == 'prev' else 1
    if not 0 <= r + step < len(ix):
        raise HTTPException(422, 'Đây là frame đầu (cuối) của scene, không có frame để chép.')
    j, k = ix[r + step], ix[r + 2 * step] if 0 <= r + 2 * step < len(ix) else None
    src = _labels_of(j, pilot, assist)
    if not src:
        raise HTTPException(422, f"Frame {ds.frames[j]['split']} {ds.frames[j]['split_index']} chưa có cuboid nào để chép.")
    older = (ds.frames[k], _labels_of(k, pilot, assist) or []) if k is not None else None
    existing = [b.model_dump() for b in body.boxes]
    seen = dismissed_types(src, store.feedback(pilot_key(ds.frames[j]['sample'], pilot, assist)), ds.gt_instance)
    new, stats = propagate(f, (ds.frames[j], src), older, existing, ds.sweep(i), ds.gt_instance, dismissed=seen)
    stats['carried_verdicts'] = sum(len(b['propagated']['dismissed']) for b in new)
    stats['from_frame'] = f"{ds.frames[j]['split']} {ds.frames[j]['split_index']}"
    store.log(pilot_key(f['sample'], pilot, assist), 'propagate', stats)
    return {'boxes': new, 'stats': stats}


@app.post('/api/frames/{i}/propose_missing')
def post_propose_missing(i: int, body: Boxes, pilot: str | None = None, assist: bool = True):
    """Proposals for every MISSING_3D flag of the given cuboids; one per object across cameras."""
    f = _frame(i)
    boxes = [b.model_dump() for b in body.boxes]
    flags = [x for x in _run_check(i, boxes, pilot, assist)['flags'] if x['type'] == 'MISSING_3D']
    new = [_as_box(f['sample'], p, p['cam']) for p in propose_missing(ds.sweep(i), f['cams'], flags, boxes)]
    store.log(pilot_key(f['sample'], pilot, assist), 'propose_missing', {'n_flags': len(flags), 'n_new': len(new)})
    return {'n_flags': len(flags), 'boxes': new}


@app.get('/api/feedback/summary')
def feedback_summary():
    """Reviewer verdicts per flag type (input for re-tuning the checker thresholds)."""
    return store.feedback_summary()


@app.get('/api/export')
def export(fmt: Literal['raw', 'nuscenes'] = 'raw'):
    """Every saved frame: raw = {sample: boxes} (LiDAR frame); nuscenes = detection-results JSON."""
    saved = {s: store.get_boxes(s) for s in store.labelled() if s in ds.by_sample}
    if fmt == 'raw':
        body = saved
    else:
        body = {'meta': {'use_camera': False, 'use_lidar': True, 'use_radar': False, 'use_map': False,
                         'use_external': False},
                'results': {s: to_nuscenes(ds.by_sample[s], b) for s, b in saved.items()}}
    return JSONResponse(body, headers={'Content-Disposition': f'attachment; filename="m44_labels_{fmt}.json"'})


@app.post('/api/frames/{i}/suggest')
def post_suggest(i: int, body: SuggestReq):
    """Fix suggestion for one flag (geometric, no LLM): what to change and the numbers behind it."""
    import uuid
    f = _frame(i)
    s = suggest(body.flag, [b.model_dump() for b in body.boxes], f, ds.dets(f['sample']), ds.sweep(i), CFG)
    return {**s, 'id': uuid.uuid4().hex[:8], 'flag': body.flag}


@app.post('/api/assistant/chat')
def assistant_chat(body: ChatReq):
    """One chat turn with the Claude assistant, streamed as server-sent events (text / tool / suggestion / error / done)."""
    ok, why = assistant.available()
    if not ok:
        raise HTTPException(503, why)
    f = _frame(body.frame_index)
    boxes = [b.model_dump() for b in body.boxes]
    ctx = assistant.Context(f, boxes, ds.dets(f['sample']), ds.sweep(body.frame_index), CFG, body.selected,
                            body.active_flag, _run_check(body.frame_index, boxes))
    return StreamingResponse(assistant.chat(body.session_id, body.message, ctx), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/assistant/reset')
def assistant_reset(body: dict):
    assistant.reset(str(body.get('session_id', '')))
    return {'ok': True}


@app.get('/api/config')
def get_config():
    ok, why = assistant.available()
    return {'cfg': CFG, 'lidar_qc': LQC, 'nusc_root': NUSC_ROOT, 'n_frames': len(ds.frames),
            'llm': {'available': ok, 'reason': why, 'model': assistant.MODEL}}


# production build of the frontend (npm run build), served at /
DIST = ROOT / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='frontend')
