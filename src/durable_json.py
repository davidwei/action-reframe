"""Durable atomic JSON commits and evidence-preserving cache quarantine."""
import hashlib
import json
import os
from pathlib import Path
import uuid
import warnings


def sync_directory(path):
    if os.name == 'nt':return
    fd=os.open(str(path),os.O_RDONLY | getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


def ensure_directory(path):
    path=Path(path)
    if path.exists():return
    ensure_directory(path.parent)
    path.mkdir(exist_ok=True)
    sync_directory(path.parent)


def write_json(path,value):
    path=Path(path);ensure_directory(path.parent)
    blob=json.dumps(value,allow_nan=False).encode()
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(blob);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path);sync_directory(path.parent)
    finally:temp.unlink(missing_ok=True)


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def quarantine(path,reason):
    path=Path(path);archive=path.with_name(path.name+'.corrupt.'+uuid.uuid4().hex)
    os.replace(path,archive);sync_directory(path.parent)
    warnings.warn(f'Corrupt cache quarantined at {archive}: {reason}; recomputing',RuntimeWarning)
    return archive
