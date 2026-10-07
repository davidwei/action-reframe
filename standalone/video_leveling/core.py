"""Portable persistence, budget accounting and CFR video indexing."""
import contextlib,fcntl,hashlib,json,os,time
from pathlib import Path
import av
import numpy as np

VERSION=1


def nominal_rate(stream):
    """Use timestamp cadence, not container frame-count divided by duration.

    Some DJI MOV files report an inaccurate average_rate even though every decoded
    frame follows an exact NTSC cadence.  FFmpeg's guessed/base rate represents that
    cadence; the decoder below still rejects genuinely off-grid timestamps.
    """
    for field in ('guessed_rate','base_rate','average_rate'):
        rate=getattr(stream,field,None)
        if rate is not None and float(rate)>0:return rate
    raise ValueError('Video stream has no usable frame rate')

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:json.dump(value,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def load(path,default=None):
    path=Path(path)
    if not path.exists():return default
    try:return json.loads(path.read_text())
    except (ValueError,OSError):
        path.rename(path.with_suffix(path.suffix+f'.corrupt-{time.time_ns()}'));return default

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def fingerprint(path):
    path=Path(path);s=path.stat();h=hashlib.sha256()
    with path.open('rb') as f:
        h.update(f.read(1024*1024));f.seek(max(0,s.st_size-1024*1024));h.update(f.read())
    return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,edge_sha256=h.hexdigest())

def probe(path):
    with av.open(str(path)) as c:
        s=c.streams.video[0];rate=nominal_rate(s);fps=float(rate);duration=float(s.duration*s.time_base) if s.duration else c.duration/1e6
        frames=max(1,round(duration*fps))
        return dict(width=s.width,height=s.height,fps=fps,rate=str(rate),average_rate=str(s.average_rate) if s.average_rate else None,
                    duration_seconds=duration,frames=frames,declared_frames=s.frames or None,codec=s.codec_context.name,
                    start_seconds=float((s.start_time or 0)*s.time_base),timeline='CFR presentation timestamps; gaps retain original indices')

@contextlib.contextmanager
def lock(folder):
    Path(folder).mkdir(parents=True,exist_ok=True)
    with (Path(folder)/'job.lock').open('w') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);yield

class Job:
    def __init__(self,video,out,hours,options=None):
        self.out=Path(out).resolve();self.out.mkdir(parents=True,exist_ok=True);video=Path(video).resolve()
        config=dict(version=VERSION,video=str(video),source=fingerprint(video),metadata=probe(video),budget_seconds=hours*3600,
            base_fps=.5,motion_fps=5.,motion_width=640,chunk_seconds=60,max_anchor_gap_seconds=30.,primary_seconds=2.5,review_seconds=5.,request_timeout=90)
        config.update(options or {})
        if hours<=0:raise ValueError('Budget must be positive')
        old=load(self.out/'config.json')
        immutable=lambda value:{k:v for k,v in value.items() if k!='budget_seconds'}
        if old and digest(immutable(old))!=digest(immutable(config)):
            raise ValueError('Output belongs to different input/settings. Use a new output folder.')
        self.config=config;self.meta=config['metadata'];save(self.out/'config.json',config)
        self.state=load(self.out/'state.json',dict(seconds={},stages={},started=time.time()))
    def remaining(self):return max(0,self.config['budget_seconds']-sum(self.state['seconds'].values()))
    def spent(self,stage):return self.state['seconds'].get(stage,0)
    def charge(self,stage,seconds):
        self.state['seconds'][stage]=self.spent(stage)+seconds;self.persist()
    def persist(self):self.state['updated']=time.time();save(self.out/'state.json',self.state)
    def status(self,stage,status,**fields):
        self.state['stages'][stage]=dict(status=status,**fields);self.persist()
        print(json.dumps(dict(video=Path(self.config['video']).name,stage=stage,status=status,remaining_seconds=round(self.remaining()),**fields)),flush=True)
    @contextlib.contextmanager
    def timed(self,stage):
        start=time.monotonic()
        try:yield
        finally:self.charge(stage,time.monotonic()-start)
    def intervals(self):
        end=self.meta['frames'];n=max(1,round(self.config['chunk_seconds']*self.meta['fps']))
        return [(i,min(end,i+n)) for i in range(0,end,n)]

    def set_models(self, primary, review):
        models=dict(primary=primary,review=review)
        old=load(self.out/'models.json')
        if old and old!=models:
            raise ValueError('This output was initialized with different models. Use a new output folder so cached model evidence is never mixed.')
        save(self.out/'models.json',models)

def decode(job,start,end):
    """Seek independently per chunk. Never renumber after damaged packets/frames."""
    m=job.meta;fps=m['fps'];errors=[]
    with av.open(job.config['video']) as c:
        stream=c.streams.video[0];stream.thread_type='AUTO';stream.codec_context.thread_count=4
        if start:c.seek(int((start/fps+m['start_seconds'])/stream.time_base),stream=stream,backward=True)
        for packet in c.demux(stream):
            try:frames=packet.decode()
            except av.error.FFmpegError as e:errors.append(str(e));continue
            for frame in frames:
                if frame.pts is None:continue
                t=float(frame.pts*frame.time_base)-m['start_seconds'];index=round(t*fps)
                if abs(t-index/fps)>.25/fps:raise ValueError('Variable frame rate is not supported by annotation v1; transcode to CFR first.')
                if index<start:continue
                if index>=end:return
                if getattr(frame,'is_corrupt',False):continue
                yield index,t,frame


def read_samples(job):
    rows=[]
    for p in sorted((job.out/'samples').glob('*.json')):
        value=load(p)
        if value:rows.extend(value['samples'])
    return sorted(rows,key=lambda r:r['frame'])
