"""Assemble the Hugging Face Space folder: the repo files (as git sees them, so nothing ignored such as .venv, cache
or API keys), the demo data, the Dockerfile and the Space card at the root.

    .venv\\Scripts\\python.exe deploy/hf/stage_space.py --data D:/m44-demo-data --out D:/m44-space
then upload the folder (see deploy/hf/README.md).
"""
import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HF = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help='output of make_demo_data.py')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    files = subprocess.run(['git', '-c', f'safe.directory={ROOT.as_posix()}', 'ls-files', '-co', '--exclude-standard'],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    n = 0
    for f in files:
        src = ROOT / f
        if f.startswith('deploy/') or not src.is_file():
            continue
        dst = out / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    shutil.copy2(HF / 'Dockerfile', out / 'Dockerfile')
    shutil.copy2(HF / 'SPACE_README.md', out / 'README.md')
    shutil.copytree(args.data, out / 'demo_data', ignore=shutil.ignore_patterns('*.db'))
    print(f'{n} repo files + demo_data -> {out}')


if __name__ == '__main__':
    main()
