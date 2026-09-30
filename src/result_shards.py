"""Immutable result shards committed by an atomic checkpoint manifest."""
import hashlib
import json
import time
import uuid
from pathlib import Path


def load_checkpoint(path):
    path=Path(path);state=json.loads(path.read_text())
    if 'result_shards' in state:
        results={}
        for name in state['result_shards']['files'].values():
            shard=(path.parent/name).resolve()
            if not shard.is_relative_to(path.parent.resolve()):raise ValueError('Invalid shard path')
            results.update(json.loads(shard.read_text()))
        state['results']=results
    return state


class ResultShards:
    def __init__(self,folder,size=180):
        if isinstance(size,bool) or int(size)!=size or size<1:raise ValueError('result_shard_frames must be a positive integer')
        self.folder=Path(folder);self.size=int(size);self.previous={};self.files={}
        (self.folder/'result_shards').mkdir(exist_ok=True)

    def save(self,path,state,writer):
        groups={}
        for frame,row in state['results'].items():groups.setdefault(str(int(frame)//self.size),{})[frame]=row
        files={}
        for group,rows in groups.items():
            previous=self.previous.get(group,{})
            unchanged=rows.keys()==previous.keys() and all(rows[k] is previous[k] for k in rows)
            if unchanged:files[group]=self.files[group];continue
            name='result_shards/'+group+'_'+uuid.uuid4().hex+'.json'
            writer(self.folder/name,rows);files[group]=name
        snapshot=dict(state,result_shards=dict(version=1,frames_per_shard=self.size,files=files),checkpoint_updated_at=time.time())
        snapshot.pop('results',None)
        writer(path,snapshot)
        # Keep references alive; scheduler replaces result rows rather than mutating them.
        self.previous=groups;self.files=files


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
