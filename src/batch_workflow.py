"""Persistent folder preparation and serial, restartable batch jobs.

Workers and job runners are separate processes. Advisory locks prevent duplicate
workers/runners; SQLite owns lifecycle state. Each job gets an immutable input
snapshot and an isolated output directory. Retry reuses that snapshot and cache.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

SOURCE = Path(__file__).resolve().parent
VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.avi'}


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.replace(path)


@contextmanager
def file_lock(path):
    """Process lifetime lock; OS releases it even after a worker crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        yield False
        return
    try:
        yield True
    finally:
        if os.name == 'nt':
            f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


class Batch:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = self.root / '.batch'
        self.folder.mkdir(exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS preparations (project TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    revision TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    updated REAL NOT NULL, config TEXT NOT NULL, error TEXT, attempts INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT OR IGNORE INTO settings VALUES ('paused','1');
            ''')

    def db(self):
        db = sqlite3.connect(self.folder / 'queue.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Path must be within this video folder')
        return path

    def inputs(self, project):
        config = read(self.path(project))
        if not isinstance(config, dict) or not all(k in config for k in ('video','output_dir','target','reference_box')):
            raise ValueError('Not a video project')
        self.path(config['video']); out = self.path(config['output_dir'])
        labels = read(out / 'corrections.json', {})
        # Include source identity without hashing an entire long video.
        video = self.path(config['video'])
        source = {'size':video.stat().st_size, 'mtime_ns':video.stat().st_mtime_ns} if video.exists() else None
        revision = hashlib.sha256(json.dumps([config, labels, source], sort_keys=True).encode()).hexdigest()
        return config, labels, revision

    def preparation(self, project):
        with self.db() as db:
            row = db.execute('SELECT payload FROM preparations WHERE project=?', (project,)).fetchone()
        return json.loads(row[0]) if row else {}

    def validate(self, config):
        import cv2
        video = self.path(config['video'])
        cap = cv2.VideoCapture(str(video))
        width, height, fps, frames = cap.get(3), cap.get(4), cap.get(5), cap.get(7)
        cap.release()
        if min(width,height,fps,frames) <= 0: raise ValueError('Video cannot be decoded')
        box = config['reference_box']
        if not isinstance(box,list) or len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):
            raise ValueError('Draw a reference box first')
        if not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height): raise ValueError('Reference box is outside the video')
        timestamp = float(config.get('reference_time',0))
        if not math.isfinite(timestamp) or not 0<=timestamp<frames/fps: raise ValueError('Reference time is outside the video')
        if not str(config['target']).strip(): raise ValueError('Target instructions are required')
        from reframe import set_analysis_fps
        set_analysis_fps(dict(config),source_fps=fps)
        if config.get('tracking_mode','single') not in ('single','dual','anchor'):raise ValueError('Unsupported tracking mode')

    def prepare(self, project, description, ready=False):
        config, _, revision = self.inputs(project)
        description = str(description).strip()
        if ready:
            self.validate(config)
            if not description: raise ValueError('Review and approve an identity description first')
        payload = dict(description=description, ready=bool(ready), revision=revision,
                       approved_at=time.time() if ready else None)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO preparations VALUES (?,?)',(project,json.dumps(payload)))
        return payload

    def library(self):
        projects=[]
        for path in sorted(self.root.glob('*.json')):
            try:
                c, labels, rev = self.inputs(path.name)
                prep = self.preparation(path.name)
                projects.append(dict(project=path.name,video=c['video'],target=c['target'],
                    reference_time=c.get('reference_time',0),reference_box=c['reference_box'],
                    labels=len(labels),description=prep.get('description',''),
                    ready=bool(prep.get('ready') and prep.get('revision')==rev),
                    stale=bool(prep.get('ready') and prep.get('revision')!=rev),
                    analysis_fps=c.get('analysis_fps'),tracking_mode=c.get('tracking_mode','single')))
            except (ValueError,OSError,TypeError,KeyError):
                continue
        videos=[str(p.relative_to(self.root)) for p in sorted(self.root.iterdir()) if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES]
        jobs=self.jobs()
        for job in jobs:
            c=read(self.path(job['config']));out=self.path(c['output_dir'])
            job['progress']=read(out/'analysis_progress.json',{})
            flags=read(out/'review_flags.json',[])
            job['review_count']=len(flags) if isinstance(flags,(list,dict)) else 0
            job['comparison_available']=(out/'comparison.mp4').exists()
            job['output_dir']=str(out.relative_to(self.root))
            job['pending_corrections']=(out/'review_corrections.json').exists()
        return dict(projects=projects,videos=videos,jobs=jobs,paused=self.paused())

    def jobs(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY created')]

    def active(self):
        return any(j['status'] in ('starting','running') for j in self.jobs())

    def enqueue(self, projects):
        if not projects: raise ValueError('Select at least one ready project')
        # Validate the entire selection before adding any jobs.
        prepared=[]
        for project in dict.fromkeys(projects):
            c,labels,rev=self.inputs(project);prep=self.preparation(project)
            if not prep.get('ready') or prep.get('revision')!=rev: raise ValueError(f'{project}: approve current inputs before queuing')
            self.validate(c);prepared.append((project,c,labels,rev,prep))
        ids=[]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for project,c,labels,rev,prep in prepared:
                revision=hashlib.sha256((rev+prep['description']).encode()).hexdigest()
                existing=db.execute("SELECT id FROM jobs WHERE project=? AND revision=? AND status IN ('queued','starting','running')",(project,revision)).fetchone()
                if existing:ids.append(existing[0]);continue
                job_id=uuid.uuid4().hex
                out=self.root/'outputs'/'batch'/job_id
                config_path=self.folder/'runs'/job_id/'project.json'
                snapshot=dict(c,video=str(self.path(c['video'])),output_dir=str(out),
                    approved_target_description=prep['description'],batch_input_revision=revision)
                write(config_path,snapshot);write(out/'corrections.json',labels)
                source_stat=self.path(c['video']).stat()
                write(config_path.parent/'inputs.json',dict(project=project,revision=revision,preparation=prep,config=c,labels=labels,
                    source_stat={'size':source_stat.st_size,'mtime_ns':source_stat.st_mtime_ns}))
                relative=str(config_path.relative_to(self.root));now=time.time()
                db.execute('INSERT INTO jobs (id,project,revision,status,created,updated,config) VALUES (?,?,?,?,?,?,?)',
                    (job_id,project,revision,'queued',now,now,relative));ids.append(job_id)
        return ids

    def adopt(self, job_id):
        job=next((j for j in self.jobs() if j['id']==job_id),None)
        if not job or job['status'] in ('queued','starting','running'):raise ValueError('Review a finished run before copying corrections')
        manifest=read(self.path(job['config']).parent/'inputs.json')
        config,_,revision=self.inputs(job['project'])
        if revision!=manifest['preparation']['revision']:
            raise ValueError('Source project changed since this run; review and merge labels manually to avoid overwriting newer work')
        run=read(self.path(job['config']))
        out=self.path(run['output_dir'])
        labels=read(out/'review_corrections.json',read(out/'corrections.json',{}))
        write(self.path(config['output_dir'])/'corrections.json',labels)
        self.prepare(job['project'],manifest['preparation']['description'],False)
        return {'project':job['project'],'labels':len(labels)}

    def paused(self):
        with self.db() as db:return db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='1'

    def pause(self, value=True):
        with self.db() as db:db.execute("UPDATE settings SET value=? WHERE key='paused'",('1' if value else '0',))

    def action(self, job_id, action):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise ValueError('Unknown job')
            if action=='retry' and row['status'] in ('failed','interrupted'):
                manifest=read(self.path(row['config']).parent/'inputs.json')
                run=read(self.path(row['config']))
                if read(self.path(run['output_dir'])/'corrections.json',{})!=manifest['labels']:
                    raise ValueError('Labels changed: copy corrections to the source and queue a new revision instead of retrying old inputs')
                db.execute("UPDATE jobs SET status='queued',error=NULL,updated=? WHERE id=?",(time.time(),job_id))
            elif action=='cancel' and row['status']=='queued':
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?",(time.time(),job_id))
            else:raise ValueError('Only queued jobs can be cancelled; failed/interrupted jobs can be retried')

    def recover(self):
        # Only the workspace worker calls this while holding its singleton lock.
        for job in self.jobs():
            if job['status'] not in ('starting','running'):continue
            with file_lock(self.folder/'locks'/(job['id']+'.lock')) as acquired:
                if acquired:
                    with self.db() as db:db.execute("UPDATE jobs SET status='interrupted',error=?,updated=? WHERE id=? AND status IN ('starting','running')",
                        ('Runner stopped before recording completion; retry resumes cached work.',time.time(),job['id']))

    def start(self):
        self.pause(False)
        with (self.folder/'worker.log').open('a') as log:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--workspace',str(self.root),'--worker'],
                             stdout=log,stderr=subprocess.STDOUT,start_new_session=True)

    def worker(self):
        with file_lock(self.folder/'worker.lock') as acquired:
            if not acquired:return
            self.recover()
            while not self.paused():
                if self.active():
                    # A runner survived a previous worker/UI restart.
                    time.sleep(1);self.recover();continue
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='1':return
                    row=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if not row:return
                    db.execute("UPDATE jobs SET status='starting',updated=? WHERE id=?",(time.time(),row['id']))
                subprocess.run([sys.executable,str(Path(__file__).resolve()),'--workspace',str(self.root),'--execute',row['id']])
                self.recover()

    def execute(self, job_id, command=None):
        # Keep the run lock across the actual processor, even if the scheduler dies.
        with file_lock(self.folder/'locks'/(job_id+'.lock')) as acquired:
            if not acquired:return
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
                if not row or row['status']!='starting':return
                db.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated=? WHERE id=?",(time.time(),job_id))
            config=self.path(row['config']);c=read(config);out=self.path(c['output_dir'])
            try:
                manifest=read(config.parent/'inputs.json')
                stat=self.path(c['video']).stat()
                if manifest['source_stat']!={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}:
                    raise ValueError('Source video changed after queuing; prepare and queue a new input revision')
                if read(out/'corrections.json',{})!=manifest['labels']:
                    raise ValueError('Run labels changed before processing; copy corrections to source and queue a new revision')
                # Run processing in this runner process: no orphan processor if it dies.
                with (out/'job.log').open('a') as log:
                    if command is not None:  # Test seam for deterministic job lifecycle checks.
                        code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode
                    else:
                        import runpy
                        with __import__('contextlib').redirect_stdout(log), __import__('contextlib').redirect_stderr(log):
                            sys.argv=[str(SOURCE/'reframe.py'),str(config),'--stage','all']
                            runpy.run_path(str(SOURCE/'reframe.py'),run_name='__main__')
                        code=0
                if code:raise RuntimeError(f'Processor exited with code {code}; see job log')
                status,error='succeeded',None
            except BaseException as exc:
                status,error='failed',f'{type(exc).__name__}: {exc}'
            with self.db() as db:db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE id=?',(status,error,time.time(),job_id))


def draft_description(batch, project):
    import base64
    import cv2
    from reframe import api, load_config
    config=load_config(batch.path(project));batch.validate(config)
    cap=cv2.VideoCapture(config['video']);cap.set(cv2.CAP_PROP_POS_MSEC,config['reference_time']*1000)
    ok,image=cap.read();cap.release()
    if not ok:raise ValueError('Cannot read reference frame')
    x1,y1,x2,y2=map(round,config['reference_box']);crop=image[y1:y2,x1:x2]
    ok,encoded=cv2.imencode('.jpg',crop)
    if not ok:raise ValueError('Cannot encode reference crop')
    model=api(config['api_url']+'/models')['data'][0]['id']
    response=api(config['api_url']+'/chat/completions',{'model':model,'temperature':0,'max_tokens':450,
        'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()}},
        {'type':'text','text':'Describe the selected subject for later identity matching: type, colors, shape, equipment, markings, visible parts and limitations. Blur is acceptable; do not invent unreadable details. Do not use image location or background as identity. User intent: '+config['target']+'\nReturn plain text for human review.'}]}]})
    return response['choices'][0]['message']['content']


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--execute')
    args=parser.parse_args();batch=Batch(args.workspace)
    if args.worker:batch.worker()
    elif args.execute:batch.execute(args.execute)
