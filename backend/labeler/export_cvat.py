"""Send saved frames to CVAT as a new point-cloud task (6 camera images attached, cuboids uploaded).

  pip install -r requirements-cvat.txt
  set CVAT_URL=http://localhost:8080 & set CVAT_ACCESS_TOKEN=...   (or put them in .cvat.env)
  python -m labeler.export_cvat --name "M44 labeler export"
"""
import argparse
import os
import tempfile
from pathlib import Path

from m44 import cvat_io
from m44.loader import load_frames_nusc

from .store import Store

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='M44 labeler export')
    ap.add_argument('--project-id', type=int)
    ap.add_argument('--nusc-root', default=os.environ.get('NUSC_ROOT', 'data/nuscenes'))
    args = ap.parse_args()

    store = Store(ROOT / 'cache' / 'labels.db')
    saved = store.labelled()
    if not saved:
        raise SystemExit('no saved frames yet')
    frames = [f for f in load_frames_nusc(args.nusc_root, 'all') if f['sample'] in saved]
    for f in frames:
        f['boxes'] = store.get_boxes(f['sample'])

    cvat_io.load_env(ROOT / '.cvat.env')
    with cvat_io.connect() as client, tempfile.TemporaryDirectory() as tmp:
        task = cvat_io.create_task(client, args.name, cvat_io.build_task_zip(frames, tmp), args.project_id)
        n = cvat_io.upload_boxes(task, frames)
    print(f'task {task.id}: {len(frames)} frames, {n} cuboids')


if __name__ == '__main__':
    main()
