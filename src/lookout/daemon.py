"""Independent local collector, resource sampler and daily report scheduler."""
import argparse
import ctypes
from datetime import datetime,timedelta
import fcntl
import json
from pathlib import Path
import select
import socket
import sqlite3
import time
from zoneinfo import ZoneInfo
from .events import validate
from .store import folder,settings,insert,connect
from .report import build,markdown


def event(kind,**fields):
    fields.setdefault('source','collector')
    return validate(dict(kind=kind,**fields))


def queue_events(root):
    path=Path(root)/'.batch/queue.sqlite3'
    if not path.exists():return []
    result=[]
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=.1) as queue:
        queue.row_factory=sqlite3.Row;jobs=[dict(r) for r in queue.execute('SELECT * FROM jobs')]
    with connect(root) as db:
        for j in jobs:
            previous=db.execute('SELECT status FROM job_snapshots WHERE id=?',(j['id'],)).fetchone()
            # Snapshot each transition; initial imports never imply observed user actions.
            if previous and previous[0]==j['status']:continue
            stage='unknown'
            try:
                c=json.loads((Path(root)/j['config']).read_text());out=Path(c['output_dir'])
                if not out.is_absolute():out=Path(root)/out
                p=out/'analysis_progress.json'
                stage=json.loads(p.read_text()).get('stage','unknown') if p.exists() else 'preparation'
            except (OSError,ValueError):pass
            age=max(0,time.time()-j['updated']) if j['status']=='running' else 0
            result.append(event('job',id='job-'+j['id']+'-'+str(int(j['updated']*1000)),timestamp=j['updated'],
                source='queue_snapshot' if previous is None else 'queue_transition',job=j['id'],project=Path(j['project']).stem,
                outcome=j['status'],retry=max(0,j['attempts']-1),stage=stage,duration_ms=age*1000))
            db.execute('INSERT OR REPLACE INTO job_snapshots VALUES(?,?)',(j['id'],j['status']))
    return result


class Sampler:
    def __init__(self):
        self.previous={};self.nvml=None
        try:
            self.nvml=ctypes.CDLL('libnvidia-ml.so.1')
            if self.nvml.nvmlInit_v2()!=0:self.nvml=None
        except OSError:pass
    def sample(self):
        result=[]
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():continue
            try:
                args=(entry/'cmdline').read_bytes().split(b'\0')
                if not any(a.endswith((b'/batch_workflow.py',b'/review_server.py',b'/reframe.py')) for a in args):continue
                stat=(entry/'stat').read_text().rsplit(')',1)[1].split()
                ticks=int(stat[11])+int(stat[12]);resident=int(stat[21])*__import__('os').sysconf('SC_PAGE_SIZE')
                pid=entry.name;now=time.monotonic();prev=self.previous.get(pid);self.previous[pid]=(ticks,now)
                job=''
                if b'--execute' in args:job=args[args.index(b'--execute')+1].decode()
                result.append(event('resource',metric='process.rss',value=resident,unit='bytes',job=job))
                if prev:result.append(event('resource',metric='process.cpu',value=100*(ticks-prev[0])/__import__('os').sysconf('SC_CLK_TCK')/(now-prev[1]),unit='percent',job=job))
            except (OSError,ValueError,IndexError):pass
        if self.nvml:
            class Util(ctypes.Structure):_fields_=[('gpu',ctypes.c_uint),('memory',ctypes.c_uint)]
            class Memory(ctypes.Structure):_fields_=[('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('used',ctypes.c_ulonglong)]
            count=ctypes.c_uint()
            if self.nvml.nvmlDeviceGetCount_v2(ctypes.byref(count))==0:
                for i in range(count.value):
                    handle=ctypes.c_void_p()
                    if self.nvml.nvmlDeviceGetHandleByIndex_v2(i,ctypes.byref(handle)):continue
                    util=Util();memory=Memory();power=ctypes.c_uint()
                    for metric,fn,obj,extract,unit in [('gpu.utilization','nvmlDeviceGetUtilizationRates',util,lambda x:x.gpu,'percent'),('gpu.memory','nvmlDeviceGetMemoryInfo',memory,lambda x:x.used,'bytes'),('gpu.power','nvmlDeviceGetPowerUsage',power,lambda x:x.value/1000,'watts')]:
                        if getattr(self.nvml,fn)(handle,ctypes.byref(obj))==0:result.append(event('resource',metric=metric,path=str(i),value=extract(obj),unit=unit))
        return result


def run(root):
    home=folder(root);lock=(home/'collector.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    address=home/'events.sock';address.unlink(missing_ok=True)
    receiver=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);receiver.bind(str(address));address.chmod(0o600);receiver.setblocking(False)
    pending=[];dropped=0;rejected=0;last_flush=last_sample=last_report=last_queue=0;sampler=Sampler()
    insert(root,[event('service',operation='collector.started')])
    while True:
        now=time.monotonic();config=settings(root)
        if select.select([receiver],[],[],.2)[0]:
            for _ in range(200):
                try:data=receiver.recv(4097)
                except BlockingIOError:break
                if not config['enabled']:continue
                try:
                    item=validate(json.loads(data))
                    if abs(item['timestamp']-time.time())>86400:raise ValueError('Client time outside accepted range')
                    if len(pending)>=10000:dropped+=1
                    else:pending.append(item)
                except (ValueError,TypeError):rejected+=1
        if not config['enabled']:pending.clear()
        if config['enabled'] and now-last_sample>=5:
            try:pending.extend(sampler.sample())
            except Exception:rejected+=1
            last_sample=now
        if config['enabled'] and now-last_queue>=15:
            try:pending.extend(queue_events(root))
            except (OSError,sqlite3.Error,ValueError):rejected+=1
            last_queue=now
        if now-last_flush>=1:
            if pending:
                try:insert(root,pending);pending.clear()
                except (OSError,sqlite3.Error):dropped+=len(pending);pending.clear()
            heartbeat=dict(timestamp=time.time(),enabled=config['enabled'],dropped=dropped,rejected=rejected,buffered=len(pending))
            try:
                temp=home/'heartbeat.tmp';temp.write_text(json.dumps(heartbeat));temp.replace(home/'heartbeat.json')
            except OSError:pass
            last_flush=now
        if now-last_report>=60:
            try:
                local=datetime.now(ZoneInfo(config['timezone']));today=local.date()
                with connect(root) as db:
                    earliest=db.execute('SELECT min(ts) FROM events').fetchone()[0]
                    existing={r[0] for r in db.execute('SELECT day FROM reports')}
                first=datetime.fromtimestamp(earliest,ZoneInfo(config['timezone'])).date() if earliest else today
                days=[today.isoformat()]
                if local.hour>=config['report_hour']:
                    # Catch up missing days; cap work per cycle, not retention.
                    d=first
                    while d<today and len(days)<8:
                        if d.isoformat() not in existing or d==today-timedelta(days=1):days.append(d.isoformat())
                        d+=timedelta(days=1)
                for day in days:
                    report=build(root,day);reports=home/'reports';reports.mkdir(exist_ok=True)
                    (reports/(day+'.md')).write_text(markdown(report))
            except Exception:rejected+=1
            last_report=now


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    run(parser.parse_args().workspace.resolve())
