"""Immutable dependency-addressed evidence, shared across runs; no failed results cached."""
import fcntl
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from durable_json import write_json, checksum, quarantine, ensure_directory


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def array_id(value):
    return dict(shape=list(value.shape),dtype=str(value.dtype),sha256=hashlib.sha256(value.tobytes()).hexdigest())


def locate(path):
    path=Path(path).absolute()
    for parent in (path,*path.parents):
        marker=parent/'stage_store.json'
        if marker.is_file():
            return Store(json.loads(marker.read_text())['root'],parent/'stage_usage.jsonl')
    return Store(path.parent/'.stage_records',path.parent/'stage_usage.jsonl')


def configure(c):
    out=Path(c['output_dir']);out.mkdir(parents=True,exist_ok=True)
    root=Path(c.get('stage_store_dir',out/'.stage_records')).resolve()
    marker=out/'stage_store.json'
    content=json.dumps(dict(root=str(root)))
    if not marker.exists() or marker.read_text()!=content:
        write_json(marker,dict(root=str(root)))
    return Store(root,out/'stage_usage.jsonl')


class Store:
    def __init__(self,root,usage=None):
        self.root=Path(root);self.usage=Path(usage) if usage else None

    def run(self,stage,version,inputs,compute):
        key=digest(dict(stage=stage,version=version,inputs=inputs))
        folder=self.root/stage/key[:2]/key;ensure_directory(folder)
        record=folder/'record.json'
        with (folder/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            reused=record.exists();started=time.monotonic()
            if reused:
                try:
                    data=json.loads(record.read_text())
                    expected=dict(stage=stage,version=version,key=key)
                    if not isinstance(data,dict) or any(data.get(k)!=v for k,v in expected.items()):
                        raise ValueError('Stage record identity mismatch')
                    if digest(data['inputs'])!=digest(inputs):raise ValueError('Stage inputs mismatch')
                    value=data['result']
                    if 'result_checksum' in data and checksum(value)!=data['result_checksum']:
                        raise ValueError('Stage result checksum mismatch')
                    if isinstance(value,dict) and value.get('error'):
                        raise ValueError('Cached result contains an error')
                except (ValueError,KeyError,TypeError) as exc:
                    quarantine(record,exc);reused=False
            if not reused:
                value=compute(folder)
                if isinstance(value,dict) and value.get('error'):
                    raise ValueError('Failed stage results cannot be committed')
                data=dict(stage=stage,version=version,key=key,inputs=inputs,result=value,created=time.time())
                data['result_checksum']=checksum(value)
                write_json(record,data)
            if self.usage:
                self.usage.parent.mkdir(parents=True,exist_ok=True)
                line=json.dumps(dict(stage=stage,key=key,reused=reused,seconds=time.monotonic()-started,time=time.time()))+'\n'
                with self.usage.open('a') as stream:
                    fcntl.flock(stream,fcntl.LOCK_EX);stream.write(line)
        return value,dict(stage=stage,key=key,reused=reused,record=str(record))


_summaries={}


def summary(path):
    path=Path(path)
    if not path.exists():return {}
    stat=path.stat();identity=(stat.st_dev,stat.st_ino)
    old=_summaries.get(str(path))
    offset,result=(old[1],json.loads(json.dumps(old[2]))) if old and old[0]==identity and stat.st_size>=old[1] else (0,{})
    with path.open('rb') as stream:
        stream.seek(offset)
        while True:
            line=stream.readline()
            if not line or not line.endswith(b'\n'):break
            offset=stream.tell()
            try:row=json.loads(line)
            except ValueError:continue
            item=result.setdefault(row['stage'],dict(computed=0,reused=0))
            item['reused' if row['reused'] else 'computed']+=1
    _summaries[str(path)]=(identity,offset,result)
    return json.loads(json.dumps(result))
