"""Append-only source-space optical predictions, independent of crop validation."""
import json
from functools import lru_cache
from pathlib import Path


def record(folder,row):
    path=Path(folder)/'optical_motion.jsonl'
    with path.open('a') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')


@lru_cache(maxsize=8)
def _read(path,mtime,size):
    rows={}
    with open(path) as stream:
        for line in stream:
            try:row=json.loads(line)
            except ValueError:continue  # Concurrent writer may not have finished the last line.
            rows[str(row['frame'])]=row  # Latest measured attempt, including a failed attempt.
    return rows


def load(folder):
    path=Path(folder)/'optical_motion.jsonl'
    if not path.exists():return {}
    stat=path.stat()
    return _read(str(path),stat.st_mtime_ns,stat.st_size)
