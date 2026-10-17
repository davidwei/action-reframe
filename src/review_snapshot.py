"""Compressed random-access records for long-video review pages."""
import gzip
import fcntl
from functools import lru_cache
import json
from pathlib import Path
import shutil
import time
import uuid

from durable_json import write_json
from video_parts import array_items,valid_box

VERSION=1
SHARD_FRAMES=600
ARRAY_KINDS=('tracks','observations','tracking_comparison','level_comparison')
JOURNAL_KINDS=('path_candidates','optical_motion')


def _identity(out,threshold=.5):
    result={'version':VERSION,'shard_frames':SHARD_FRAMES,'confidence_threshold':float(threshold)}
    for name in ARRAY_KINDS:
        path=out/f'{name}.json'
        if path.is_file():
            stat=path.stat();result[name]=[stat.st_size,stat.st_mtime_ns]
    for name in JOURNAL_KINDS:
        path=out/f'{name}.jsonl'
        if path.is_file():
            stat=path.stat();result[name]=[stat.st_size,stat.st_mtime_ns]
    return result


def _accepted(row,threshold):
    if row.get('manual'):return bool(row.get('bbox'))
    verification=row.get('box_verification') or {}
    if verification.get('version',0)>=7 and not (verification.get('decision') or {}).get('accepted'):return False
    return valid_box(row.get('bbox')) and float(row.get('confidence') or 0)>=threshold and not row.get('error') and not row.get('scene_cut') and row.get('visibility') not in ('absent','uncertain')


def _write_group(folder,kind,group,rows):
    path=folder/f'{kind}_{group:06d}.json.gz'
    with gzip.open(path,'wt',encoding='utf-8',compresslevel=5) as stream:json.dump(rows,stream,separators=(',',':'),allow_nan=False)


def build(output,meta=None,rows=None,threshold=.5):
    """Build only derived review data; analysis and render artifacts remain unchanged."""
    out=Path(output);meta=meta or json.loads((out/'meta.json').read_text());identity=_identity(out,threshold)
    final=out/'review_snapshot';temporary=out/f'.review_snapshot.{uuid.uuid4().hex}'
    temporary.mkdir()
    navigation={'sampled':[],'tracked':[],'highqualitytracked':[]}
    try:
        for kind in ARRAY_KINDS:
            path=out/f'{kind}.json'
            if not path.is_file() and not (kind=='tracks' and rows is not None):continue
            source=iter(rows) if kind=='tracks' and rows is not None else array_items(path)
            group=None;bucket={};last=-1
            for expected,row in enumerate(source):
                frame=int(row.get('frame',expected))
                if 'frame' not in row:row=dict(row,frame=frame)
                if frame<last:raise ValueError(f'{kind} records are not frame ordered')
                last=frame;next_group=frame//SHARD_FRAMES
                if group is not None and next_group!=group:
                    _write_group(temporary,kind,group,bucket);bucket={}
                group=next_group;bucket[str(frame)]=row
                if kind=='tracks' and valid_box(row.get('bbox')) and float(row.get('crop_width') or 0)*float(row.get('crop_height') or 0)>=240000:navigation['highqualitytracked'].append(frame)
                if kind=='observations':
                    if not row.get('manual'):navigation['sampled'].append(frame)
                    if _accepted(row,threshold):navigation['tracked'].append(frame)
            if group is not None:_write_group(temporary,kind,group,bucket)
        journal_indexes={}
        for kind in JOURNAL_KINDS:
            path=out/f'{kind}.jsonl'
            if not path.is_file():continue
            offsets={}
            with path.open('rb') as stream:
                while True:
                    offset=stream.tell();line=stream.readline()
                    if not line:break
                    try:frame=int(json.loads(line).get('frame'))
                    except (ValueError,TypeError,AttributeError):continue
                    offsets.setdefault(str(frame),[]).append(offset)
            journal_indexes[kind]=offsets
        manifest={'identity':identity,'frames':int(meta['frames']),'fps':float(meta['fps']),'navigation':navigation,
            'journal_indexes':journal_indexes,'created_at':time.time()}
        write_json(temporary/'manifest.json',manifest)
        if final.exists():shutil.rmtree(final)
        temporary.replace(final)
        return manifest
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True);raise


def ensure(output,meta=None,rows=None,threshold=.5):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);manifest_path=out/'review_snapshot'/'manifest.json'
    def current():
        try:
            manifest=_manifest(str(manifest_path),manifest_path.stat().st_mtime_ns)
            return manifest if manifest.get('identity')==_identity(out,threshold) else None
        except (OSError,ValueError,TypeError):return None
    existing=current()
    if existing:return existing
    with (out/'review_snapshot.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        existing=current()
        if existing:return existing
        return build(out,meta,rows,threshold)


@lru_cache(maxsize=16)
def _manifest(path,mtime_ns):
    return json.loads(Path(path).read_text())


def status(output,threshold=.5):
    out=Path(output);path=out/'review_snapshot'/'manifest.json'
    try:
        manifest=_manifest(str(path),path.stat().st_mtime_ns)
        return {'ready':manifest.get('identity')==_identity(out,threshold),'created_at':manifest.get('created_at'),'navigation':manifest.get('navigation',{})}
    except (OSError,ValueError,TypeError):return {'ready':False,'navigation':{}}


@lru_cache(maxsize=24)
def _read_shard(path,mtime_ns):
    with gzip.open(path,'rt',encoding='utf-8') as stream:return json.load(stream)


def _shard(out,kind,frame):
    path=out/'review_snapshot'/f'{kind}_{frame//SHARD_FRAMES:06d}.json.gz'
    if not path.is_file():return None
    return _read_shard(str(path),path.stat().st_mtime_ns).get(str(frame))


def _journal_rows(out,kind,frame,manifest):
    path=out/f'{kind}.jsonl';result=[]
    if not path.is_file():return result
    with path.open('rb') as stream:
        for offset in manifest.get('journal_indexes',{}).get(kind,{}).get(str(frame),[]):
            stream.seek(offset)
            try:result.append(json.loads(stream.readline()))
            except ValueError:continue
    return result


def frame(output,index,threshold=.5,meta=None):
    out=Path(output);meta=meta or json.loads((out/'meta.json').read_text());index=int(index)
    if not 0<=index<int(meta['frames']):raise ValueError('Frame out of range')
    manifest=ensure(out,meta,threshold=threshold)
    candidates={}
    for entry in _journal_rows(out,'path_candidates',index,manifest):
        for key,value in entry.get('candidates',{}).items():
            old=candidates.get(key)
            if old is None or not old.get('bbox') or value.get('bbox') and value.get('confidence',0)>=old.get('confidence',0):candidates[key]=value
    optical_rows=_journal_rows(out,'optical_motion',index,manifest)
    failures=[]
    path=out/'analysis_failures.json'
    if path.is_file():failures=[row for row in json.loads(path.read_text()) if int(row.get('frame',-1))==index]
    return {'frame':index,'track':_shard(out,'tracks',index),'observation':_shard(out,'observations',index),
        'tracking_comparison':_shard(out,'tracking_comparison',index),'level_comparison':_shard(out,'level_comparison',index),
        'path_candidates':candidates,'optical_motion':optical_rows[-1] if optical_rows else None,'analysis_failures':failures}
