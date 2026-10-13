"""API smoke test against a running backend (needs nuScenes-mini). Read-only except one 'propagate' row in the event log.

    cd backend && ..\\.venv\\Scripts\\python.exe -m uvicorn labeler.main:app --port 8771
    .venv\\Scripts\\python.exe tests/smoke_api.py --url http://127.0.0.1:8771
"""
import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request

URL = 'http://127.0.0.1:8771'
FRAME = 1  # val 1: a mid-scene keyframe, so the temporal checks have neighbours on both sides


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return r.status, r.headers.get('Content-Type', ''), raw
    except urllib.error.HTTPError as e:
        return e.code, '', e.read()


def get_json(path: str):
    status, _, raw = call('GET', path)
    assert status == 200, (path, status, raw[:200])
    return json.loads(raw)


def check(boxes):
    status, _, raw = call('POST', f'/api/frames/{FRAME}/check', {'boxes': boxes})
    assert status == 200, (status, raw[:200])
    return json.loads(raw)


def flagged(res, box_id):
    return [f['type'] for f in res['flags'] if f.get('box_id') == box_id]


def test_list_frames():
    frames = get_json('/api/frames')
    if get_json('/api/config').get('demo'):  # the public demo ships the mini val scenes only
        assert len(frames) == 81 and all(f['split'] == 'val' for f in frames), len(frames)
        return f'{len(frames)} frame val (bản demo)'
    assert len(frames) == 404, len(frames)
    assert [f['split'] for f in frames[:81]] == ['val'] * 81 and frames[81]['split'] == 'train'
    return f'{len(frames)} frame (81 val + 323 train)'


def test_get_frame(f):
    assert len(f['cams']) == 6 and f['boxes'], 'cams / boxes'
    assert set(f['qc']) == {b['box_id'] for b in f['boxes']}, 'qc for every cuboid'
    assert set(f['coverage']) == {'camera', 'lidar', 'track', 'any'}
    assert all(x['certainty'] in ('sure', 'review') for x in f['flags'])
    return f"{len(f['boxes'])} cuboid, {len(f['flags'])} cờ, độ phủ {f['coverage']}"


def test_points():
    status, _, raw = call('GET', f'/api/frames/{FRAME}/points')
    assert status == 200 and raw and len(raw) % 16 == 0, (status, len(raw))
    return f'{len(raw) // 16} điểm (float32 x, y, z, intensity)'


def test_image():
    status, ctype, raw = call('GET', f'/api/frames/{FRAME}/image/CAM_FRONT')
    assert status == 200 and raw[:2] == b'\xff\xd8', (status, ctype)
    return f'JPEG {len(raw) // 1024} KB'


def test_check_deterministic(f):
    a, b = check(f['boxes']), check(f['boxes'])
    ka = sorted((x['type'], x.get('box_id')) for x in a['flags'])
    assert ka == sorted((x['type'], x.get('box_id')) for x in b['flags'])
    assert len(a['flags']) == len(f['flags']), (len(a['flags']), len(f['flags']))
    return f"{len(a['flags'])} cờ, giống hệt GET"


def _clean_car(f, need):
    """A car no source flags and that the given sources have checked."""
    hit = {x.get('box_id') for x in f['flags']}
    for b in f['boxes']:
        q = f['qc'][b['box_id']]
        if b['cls'] == 'car' and b['box_id'] not in hit and all(q[s] == 'ok' for s in need):
            return b
    raise AssertionError(f'no clean car checked by {need}')


def test_shift_flagged(f):
    car = _clean_car(f, ['camera'])
    boxes = [dict(b, center=[b['center'][0] + 2.5, b['center'][1], b['center'][2]]) if b is car else b
             for b in f['boxes']]
    types = flagged(check(boxes), car['box_id'])
    assert types, 'shifted car not flagged'
    return f"dời {car['box_id']} 2,5 m → {sorted(set(types))}"


def test_flip_flagged(f):
    car = _clean_car(f, ['track'])
    boxes = [dict(b, yaw=b['yaw'] + math.pi) if b is car else b for b in f['boxes']]
    types = flagged(check(boxes), car['box_id'])
    assert 'TRACK_YAW' in types, types
    return f"quay ngược {car['box_id']} 180° → {sorted(set(types))}"


def test_missing_flagged(f):
    car = _clean_car(f, ['track'])
    res = check([b for b in f['boxes'] if b is not car])
    miss = [x for x in res['flags'] if x['type'] in ('TRACK_MISSING', 'LIDAR_UNBOXED', 'MISSING_3D')
            and math.dist(x.get('detail', {}).get('box', {}).get('center', [1e9, 1e9])[:2], car['center'][:2]) < 2.0]
    assert miss, 'deleted car not reported as missing'
    return f"xoá {car['box_id']} → {sorted({x['type'] for x in miss})} tại đúng chỗ"


def test_suggest(f):
    car = _clean_car(f, ['track'])
    boxes = [dict(b, yaw=b['yaw'] + math.pi) if b is car else b for b in f['boxes']]
    flag = next(x for x in check(boxes)['flags'] if x.get('box_id') == car['box_id'] and x['type'] == 'TRACK_YAW')
    status, _, raw = call('POST', f'/api/frames/{FRAME}/suggest', {'flag': flag, 'boxes': boxes})
    assert status == 200, (status, raw[:200])
    s = json.loads(raw)
    assert s['action'] == 'update' and s.get('box'), s
    dyaw = abs((s['box']['yaw'] - car['yaw'] + math.pi) % (2 * math.pi) - math.pi)
    assert dyaw < math.radians(15), math.degrees(dyaw)
    return f"gợi ý sửa đưa hướng về lệch {math.degrees(dyaw):.1f}° so với nhãn gốc"


def test_propagate(f):
    status, _, raw = call('POST', f'/api/frames/{FRAME}/propagate', {'boxes': [], 'direction': 'prev'})
    assert status == 200, (status, raw[:200])
    new = json.loads(raw)['boxes']
    assert new and all(b.get('instance') for b in new)
    return f'chép {len(new)} cuboid từ frame trước, giữ mã vật'


def test_errors():
    assert call('GET', '/api/frames/99999')[0] == 404
    assert call('GET', f'/api/frames/{FRAME}/image/CAM_NOPE')[0] in (404, 422)
    assert call('POST', f'/api/frames/{FRAME}/check', {'boxes': [{'box_id': 'x'}]})[0] == 422
    return 'frame sai → 404, camera sai → 404/422, cuboid thiếu trường → 422'


def test_latency(f):
    ms = []
    for _ in range(10):
        t = time.perf_counter()
        check(f['boxes'])
        ms.append((time.perf_counter() - t) * 1000)
    med = statistics.median(ms)
    assert med < 500, med
    return f"POST /check: trung vị {med:.0f} ms, max {max(ms):.0f} ms ({len(f['boxes'])} cuboid)"


def main():
    global URL
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=URL)
    URL = ap.parse_args().url.rstrip('/')
    f = get_json(f'/api/frames/{FRAME}?source=gt')
    tests = [('list_frames', test_list_frames), ('get_frame', lambda: test_get_frame(f)), ('points', test_points),
             ('image', test_image), ('check_deterministic', lambda: test_check_deterministic(f)),
             ('shift_flagged', lambda: test_shift_flagged(f)), ('flip_flagged', lambda: test_flip_flagged(f)),
             ('missing_flagged', lambda: test_missing_flagged(f)), ('suggest', lambda: test_suggest(f)),
             ('propagate', lambda: test_propagate(f)), ('errors', test_errors), ('latency', lambda: test_latency(f))]
    failed = 0
    for name, fn in tests:
        try:
            print(f'ok   {name}: {fn()}')
        except Exception as e:  # report every test, not just the first failure
            failed += 1
            print(f'FAIL {name}: {e!r}')
    print(f'{len(tests) - failed}/{len(tests)} passed')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
