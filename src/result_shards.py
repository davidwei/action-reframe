"""Immutable result shards committed by an atomic checkpoint manifest."""
import hashlib
import json
import time
import uuid
from pathlib import Path
import warnings
from durable_json import checksum, ensure_directory


def _load_checkpoint(path,root=None):
    path=Path(path);root=Path(root) if root is not None else path.parent;state=json.loads(path.read_text())
    if not isinstance(state,dict):raise ValueError('Checkpoint must be an object')
    expected=state.get('checkpoint_checksum')
    if expected and checksum({k:v for k,v in state.items() if k!='checkpoint_checksum'})!=expected:
        raise ValueError('Checkpoint checksum mismatch')
    if 'result_shards' in state:
        results={}
        for name in state['result_shards']['files'].values():
            shard=(root/name).resolve()
            if not shard.is_relative_to(root.resolve()):raise ValueError('Invalid shard path')
            try:
                rows=json.loads(shard.read_text())
                if not isinstance(rows,dict):raise ValueError('Shard must contain frame records')
                expected=state['result_shards'].get('checksums',{}).get(name)
                if expected and checksum(rows)!=expected:raise ValueError('Shard checksum mismatch')
                results.update(rows)
            except (OSError,ValueError) as exc:
                raise ValueError(f'Cannot read result shard {name}: {exc}') from exc
        state['results']=results
    if not isinstance(state.get('results'),dict):raise ValueError('Checkpoint has no result map')
    marker=state.get('event_journal')
    if marker:
        name=marker['file']
        if Path(name).name!=name:raise ValueError('Invalid event journal path')
        if (root/name).stat().st_size<marker['committed_bytes']:
            raise ValueError('Event journal is shorter than committed checkpoint')
        if marker.get('sha256'):
            digest=hashlib.sha256();remaining=marker['committed_bytes']
            with (root/name).open('rb') as stream:
                while remaining:
                    block=stream.read(min(1024*1024,remaining))
                    if not block:raise ValueError('Truncated event journal')
                    digest.update(block);remaining-=len(block)
            if digest.hexdigest()!=marker['sha256']:raise ValueError('Event journal checksum mismatch')
    return state


def load_checkpoint(path):
    path=Path(path)
    history=path.parent/'checkpoint_history'
    candidates=[path,path.with_name(path.name+'.previous')]
    candidates+=sorted(history.glob('*.json'),reverse=True) if history.exists() else []
    failures=[]
    for candidate in candidates:
        try:state=_load_checkpoint(candidate,path.parent)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            failures.append(f'{candidate}: {exc}');continue
        if candidate!=path:
            warnings.warn(f'Recovering complete checkpoint {candidate}; latest checkpoint invalid',RuntimeWarning)
        return state
    raise ValueError('Cannot recover checkpoint: '+'; '.join(failures))


class ResultShards:
    def __init__(self,folder,size=180):
        if isinstance(size,bool) or int(size)!=size or size<1:raise ValueError('result_shard_frames must be a positive integer')
        self.folder=Path(folder);self.size=int(size);self.previous={};self.files={};self.checksums={};self.last_snapshot=None
        ensure_directory(self.folder/'result_shards')

    def save(self,path,state,writer):
        path=Path(path)
        if self.last_snapshot is None and path.exists():
            # Only once on resume, validate the complete old generation before retaining it.
            try:
                old=load_checkpoint(path)
                if 'result_shards' in old:old.pop('results',None)
                self.last_snapshot=old
            except ValueError:
                pass  # No usable old generation; never overwrite evidence with an invented backup.
        groups={}
        for frame,row in state['results'].items():groups.setdefault(str(int(frame)//self.size),{})[frame]=row
        files={};checksums={}
        for group,rows in groups.items():
            previous=self.previous.get(group,{})
            unchanged=rows.keys()==previous.keys() and all(rows[k] is previous[k] for k in rows)
            if unchanged:
                files[group]=self.files[group];checksums[files[group]]=self.checksums[files[group]];continue
            name='result_shards/'+group+'_'+uuid.uuid4().hex+'.json'
            writer(self.folder/name,rows);files[group]=name;checksums[name]=checksum(rows)
        snapshot=dict(state,result_shards=dict(version=1,frames_per_shard=self.size,files=files,checksums=checksums),checkpoint_updated_at=time.time())
        snapshot.pop('results',None)
        snapshot.pop('checkpoint_checksum',None)
        snapshot['checkpoint_checksum']=checksum(snapshot)
        if self.last_snapshot is not None:writer(path.with_name(path.name+'.previous'),self.last_snapshot)
        writer(path,snapshot)
        self.last_snapshot=json.loads(json.dumps(snapshot))
        history=self.folder/'checkpoint_history';ensure_directory(history)
        stamp=time.time_ns()
        writer(history/f'{stamp:020d}_recent.json',snapshot)
        # Keep five recent generations plus one per hour for the last 24 saved hours.
        hourly=list(history.glob('*_hourly.json'))
        if not hourly or time.time()-max(p.stat().st_mtime for p in hourly)>=3600:
            writer(history/f'{stamp:020d}_hourly.json',snapshot)
        for kind,keep in [('recent',5),('hourly',24)]:
            for old in sorted(history.glob(f'*_{kind}.json'),reverse=True)[keep:]:old.unlink()
        # Shards are retained: active snapshot readers may still reference older files.
        # Keep references alive; scheduler replaces result rows rather than mutating them.
        self.previous=groups;self.files=files;self.checksums=checksums


def export_snapshot(folder,writer):
    import fcntl
    folder=Path(folder)
    with (folder/'analysis_snapshot.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        checkpoint=folder/'anchor_checkpoint.json'
        if not checkpoint.exists():raise ValueError('No committed analysis checkpoint is available yet')
        state=load_checkpoint(checkpoint);meta=json.loads((folder/'meta.json').read_text())
        rows=[];pairs=[]
        for index in state.get('sample_indices',sorted(map(int,state['results']))):
            row=dict(state['results'].get(str(index),dict(frame=index,time=index/meta['fps'],bbox=None,confidence=0,visibility='uncertain',selection_reason='Not examined yet',selection_flags=['tracking_unexamined'])))
            row['selected_path']=row.get('selected_path','manual' if row.get('manual') else 'neither');rows.append(row)
            candidates=row.get('candidates')
            if candidates and all(p in candidates for p in ('raw_angle','leveled')):
                pairs.append(dict(frame=index,time=row['time'],raw_angle=candidates['raw_angle'],leveled=candidates['leveled'],selected={k:v for k,v in row.items() if k!='candidates'},box_iou=row.get('box_iou')))
        for name,data in [('observations',rows),('tracking_selected',rows),('tracking_comparison',pairs)]:writer(folder/(name+'.json'),data)
        for path in ('raw_angle','leveled'):
            writer(folder/f'tracking_{path}.json',[r if r.get('manual') else r.get('candidates',{}).get(path,dict(frame=r['frame'],time=r['time'],bbox=None,confidence=0,visibility='uncertain')) for r in rows])
        info=dict(created_at=time.time(),checkpoint_updated_at=state.get('checkpoint_updated_at'),stage=state.get('stage'),frames=len(rows))
        writer(folder/'analysis_snapshot.json',info)
        return info
