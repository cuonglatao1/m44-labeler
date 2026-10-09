"""SQLite store: the current cuboids of each frame, an event log (saves, reviewer feedback on flags) and
pilot runs.

Pilot drafts live in the same tables under the key `pilot/<name>/<a|n>/<sample>` (see pilot_key), so a
pilot never touches the real labels of a frame and several people can label the same frame.
"""
import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS labels (
                sample TEXT PRIMARY KEY, boxes TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, sample TEXT,
                kind TEXT NOT NULL, data TEXT);
            CREATE TABLE IF NOT EXISTS pilot_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, name TEXT NOT NULL,
                sample TEXT NOT NULL, assist INTEGER NOT NULL, started REAL NOT NULL, submitted REAL NOT NULL,
                score TEXT NOT NULL, boxes TEXT NOT NULL);
        """)

    def get_boxes(self, sample: str) -> list[dict] | None:
        row = self.db.execute('SELECT boxes FROM labels WHERE sample = ?', (sample,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_boxes(self, sample: str, boxes: list[dict]) -> None:
        now = time.time()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO labels VALUES (?, ?, ?)', (sample, json.dumps(boxes), now))
            self.db.execute('INSERT INTO events (ts, sample, kind, data) VALUES (?, ?, ?, ?)',
                            (now, sample, 'save', json.dumps({'n_boxes': len(boxes)})))

    def labelled(self) -> set[str]:
        """Frames with saved real labels (pilot drafts excluded)."""
        return {r[0] for r in self.db.execute("SELECT sample FROM labels WHERE sample NOT LIKE 'pilot/%'")}

    def log(self, sample: str | None, kind: str, data: dict) -> None:
        with self.db:
            self.db.execute('INSERT INTO events (ts, sample, kind, data) VALUES (?, ?, ?, ?)',
                            (time.time(), sample, kind, json.dumps(data)))

    def feedback(self, sample: str) -> dict[str, str]:
        """Latest reviewer verdict per flag key on this frame: 'accept' or 'false_alarm' ('clear' removes it)."""
        out = {}
        for kind, data in self.db.execute(
                "SELECT kind, data FROM events WHERE sample = ? AND kind LIKE 'flag_%' ORDER BY id", (sample,)):
            key = json.loads(data).get('key')
            if kind == 'flag_clear':
                out.pop(key, None)
            else:
                out[key] = kind.removeprefix('flag_')
        return out

    def feedback_summary(self) -> dict[str, dict[str, int]]:
        """{flag type: {'accept': n, 'false_alarm': n}} over the latest verdict of every flag."""
        latest = {}
        for sample, kind, data in self.db.execute(
                "SELECT sample, kind, data FROM events WHERE kind LIKE 'flag_%' ORDER BY id"):
            d = json.loads(data)
            latest[(sample, d.get('key'))] = (kind.removeprefix('flag_'), d.get('type'))
        out: dict[str, dict[str, int]] = {}
        for verdict, ftype in latest.values():
            if verdict != 'clear':
                out.setdefault(ftype, {}).setdefault(verdict, 0)
                out[ftype][verdict] += 1
        return out

    # ---------- pilot ----------

    def pilot_start(self, key: str) -> float:
        """Time the pilot first opened this frame (recorded on the first call)."""
        row = self.db.execute("SELECT ts FROM events WHERE sample = ? AND kind = 'pilot_start' ORDER BY id LIMIT 1",
                              (key,)).fetchone()
        if row:
            return row[0]
        now = time.time()
        self.log(key, 'pilot_start', {})
        return now

    def pilot_submit(self, key: str, name: str, sample: str, assist: bool, score: dict, boxes: list[dict]) -> dict:
        started, now = self.pilot_start(key), time.time()
        with self.db:
            self.db.execute('INSERT INTO pilot_runs (key, name, sample, assist, started, submitted, score, boxes) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (key, name, sample, int(assist), started, now, json.dumps(score), json.dumps(boxes)))
        return self.pilot_run(key)

    def pilot_run(self, key: str) -> dict | None:
        """Latest submission for this pilot key."""
        row = self.db.execute('SELECT id FROM pilot_runs WHERE key = ? ORDER BY id DESC LIMIT 1', (key,)).fetchone()
        return self.pilot_runs(row[0])[0] if row else None

    def pilot_runs(self, run_id: int | None = None) -> list[dict]:
        q = 'SELECT id, name, sample, assist, started, submitted, score FROM pilot_runs'
        rows = self.db.execute(q + (' WHERE id = ?' if run_id else '') + ' ORDER BY id', (run_id,) if run_id else ())
        return [{'id': i, 'name': n, 'sample': s, 'assist': bool(a), 'started': st, 'submitted': sub,
                 'minutes': round((sub - st) / 60, 1), **json.loads(score)}
                for i, n, s, a, st, sub, score in rows]


def pilot_key(sample: str, pilot: str | None, assist: bool) -> str:
    """Storage key of a frame: the sample token, or the pilot's own draft of it."""
    return f"pilot/{pilot}/{'a' if assist else 'n'}/{sample}" if pilot else sample
