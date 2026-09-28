"""Record executable source identity at run start, including uncommitted changes."""
import hashlib
from pathlib import Path
import subprocess
import time

_cached=None;_at=0


def current():
    global _cached,_at
    if _cached and time.monotonic()-_at<5:return dict(_cached)
    root=Path(__file__).resolve().parent.parent;digest=hashlib.sha256()
    for folder in ('src','configs','scripts'):
        for p in sorted((root/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.html','.json','.sh'):
                digest.update(str(p.relative_to(root)).encode());digest.update(p.read_bytes())
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL,timeout=2).strip()
    except (OSError,subprocess.SubprocessError):commit=None
    _cached=dict(commit=commit,fingerprint=digest.hexdigest());_at=time.monotonic();return dict(_cached)


def comparison(saved,latest):
    if not saved:return dict(status='unknown',label='Version not recorded')
    return dict(status='current' if saved.get('fingerprint')==latest['fingerprint'] else 'older',
        label='Current code' if saved.get('fingerprint')==latest['fingerprint'] else 'Older code',commit=saved.get('commit'))
