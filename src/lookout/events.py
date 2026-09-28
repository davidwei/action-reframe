"""Bounded nonblocking event transport and inexpensive aggregated instrumentation."""
import contextlib
import contextvars
import functools
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import uuid

KINDS={'view','activity','action','edit','navigation','playback','request','ui_error','stage','model','counter','resource','job','service'}
FIELDS={'id','timestamp','kind','session','workflow','action_id','action','section','view','project','job','revision','version','outcome','duration_ms','cpu_ms','count','active_seconds','mouse','keyboard','visible','focused','length_delta','saved','stage','operation','path','frame','input_tokens','output_tokens','finish_reason','retry','cache_hit','error_kind','source','metric','value','unit','details_available','control_visible'}
TEXT={'session','workflow','action_id','action','section','view','project','job','revision','version','outcome','stage','operation','path','finish_reason','error_kind','source','metric','unit'}
_root=None;_job=None;_project=None;_version='unknown';_socket=None;_last_config=0;_enabled=True
_stage=contextvars.ContextVar('lookout_stage',default='')
_lock=threading.Lock();_counts={};_last_flush=0;_dropped=0


def validate(event):
    if not isinstance(event,dict) or set(event)-FIELDS:raise ValueError('Unknown telemetry fields')
    if event.get('kind') not in KINDS:raise ValueError('Unknown event kind')
    result=dict(event)
    result.setdefault('id',uuid.uuid4().hex);result.setdefault('timestamp',time.time())
    if not isinstance(result['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',result['id']):raise ValueError('Invalid event ID')
    for key,value in result.items():
        if key in TEXT:
            if not isinstance(value,str) or len(value)>128 or not re.fullmatch(r'[A-Za-z0-9_.:/ -]*',value):raise ValueError('Invalid telemetry label')
            if '/' in value and key in ('project','job'):raise ValueError('Use IDs, not paths')
        elif key not in ('id','kind'):
            if not isinstance(value,(int,float,bool)) or not __import__('math').isfinite(value):raise ValueError('Invalid numeric field')
    if len(json.dumps(result))>4096:raise ValueError('Event too large')
    return result


def configure(root,job=None,project=None,version=None):
    global _root,_job,_project,_version
    _root=Path(root).resolve();_job=job;_project=project
    if version:_version=version
    elif _version=='unknown':
        try:
            repo=Path(__file__).resolve().parents[2];head=(repo/'.git/HEAD').read_text().strip()
            _version=(repo/'.git'/head[5:]).read_text().strip()[:12] if head.startswith('ref: ') else head[:12]
        except OSError:pass


def root_path():
    if _root:return _root
    value=os.environ.get('LOOKOUT_WORKSPACE')
    return Path(value).resolve() if value else None


def emit(kind,**fields):
    global _socket,_last_config,_enabled,_dropped
    try:
        root=root_path()
        if root is None:return False
        now=time.monotonic()
        if now-_last_config>5:
            p=root/'.lookout/settings.json'
            _enabled=json.loads(p.read_text()).get('enabled',True) if p.exists() else True
            _last_config=now
        if not _enabled:return False
        event=dict(kind=kind,**fields)
        event.setdefault('version',_version)
        if _stage.get():event.setdefault('stage',_stage.get())
        if _job:event.setdefault('job',_job)
        if _project:event.setdefault('project',_project)
        data=json.dumps(validate(event)).encode()
        if _socket is None:
            _socket=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);_socket.setblocking(False)
        _socket.sendto(data,str(root/'.lookout/events.sock'))
        if _dropped and kind!='service':
            lost=_dropped;_dropped=0;emit('service',operation='producer.dropped',count=lost)
        return True
    except Exception:
        _dropped+=1
        return False


def count(operation,amount=1,**fields):
    global _last_flush
    try:
        with _lock:
            key=(operation,tuple(sorted(fields.items())))
            _counts[key]=_counts.get(key,0)+amount
            if time.monotonic()-_last_flush<5:return
            pending=dict(_counts);_counts.clear();_last_flush=time.monotonic()
        for (name,items),value in pending.items():emit('counter',operation=name,count=value,**dict(items))
    except Exception:pass


@contextlib.contextmanager
def span(stage):
    token=_stage.set(stage)
    start=time.monotonic();cpu=time.process_time();outcome='success'
    emit('stage',stage=stage,operation='start')
    try:yield
    except BaseException:
        outcome='error';raise
    finally:
        emit('stage',stage=stage,operation='end',duration_ms=(time.monotonic()-start)*1000,
             cpu_ms=(time.process_time()-cpu)*1000,outcome=outcome)
        _stage.reset(token)


def timed(stage):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            with span(stage):return fn(*args,**kwargs)
        return wrapped
    return decorate
