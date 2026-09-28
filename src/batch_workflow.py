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
import shutil
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
                CREATE TABLE IF NOT EXISTS project_updates (project TEXT PRIMARY KEY, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS discarded (project TEXT PRIMARY KEY, discarded_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT OR IGNORE INTO settings VALUES ('paused','1');
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'priority' not in {r[1] for r in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')

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

    def create_project(self, video):
        source=self.path(video)
        if not source.is_file() or source.suffix.lower() not in VIDEO_SUFFIXES:raise ValueError('Choose a supported video')
        config=read(SOURCE.parent/'configs/defaults.json')
        import cv2
        cap=cv2.VideoCapture(str(source));fps=cap.get(5);cap.release()
        if fps<=0:raise ValueError('Cannot read video')
        config['analysis_fps']=min(config['analysis_fps'],fps)
        name='project_'+uuid.uuid4().hex[:8]+'.json'
        config.update(video=str(source.relative_to(self.root)),output_dir='outputs/'+name[:-5],
                      reference_time=0,reference_box=None,target='',tracking_mode='anchor')
        write(self.root/name,config)
        return {'project':name}

    def discarded(self):
        with self.db() as db:return {r[0] for r in db.execute('SELECT project FROM discarded')}

    def discard(self, project):
        self.inputs(project)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO discarded VALUES (?,?)',(project,time.time()))
            db.execute('INSERT OR REPLACE INTO project_updates VALUES (?,?)',(project,time.time()))
            db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE project=? AND status='queued'",(time.time(),project))
        return {'discarded':project,'finishing':any(j['project']==project and j['status'] in ('starting','running') for j in self.jobs())}

    def restore(self, project):
        with self.db() as db:
            db.execute('DELETE FROM discarded WHERE project=?',(project,))
            db.execute('INSERT OR REPLACE INTO project_updates VALUES (?,?)',(project,time.time()))
        return {'restored':project}

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

        from reframe import set_analysis_fps
        set_analysis_fps(dict(config),source_fps=fps)
        if config.get('tracking_mode','single') not in ('single','dual','anchor'):raise ValueError('Unsupported tracking mode')

    def prepare(self, project, description, ready=False):
        if project in self.discarded():raise ValueError('Restore the discarded project before editing it')
        config, _, revision = self.inputs(project)
        description = str(description).strip()
        if ready:
            self.validate(config)
            if not description: raise ValueError('Review and approve an identity description first')
            if not config.get('target','').strip():
                config['target']=description;write(self.path(project),config)
                _,_,revision=self.inputs(project)
        payload = dict(description=description, ready=bool(ready), revision=revision,
                       approved_at=time.time() if ready else None,updated_at=time.time())
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO preparations VALUES (?,?)',(project,json.dumps(payload)))
        return payload

    def last_updated(self, project, config, preparation, jobs):
        times=[self.path(project).stat().st_mtime,preparation.get('updated_at') or preparation.get('approved_at') or 0]
        with self.db() as db:
            row=db.execute('SELECT updated_at FROM project_updates WHERE project=?',(project,)).fetchone()
            if row:times.append(row[0])
            row=db.execute('SELECT discarded_at FROM discarded WHERE project=?',(project,)).fetchone()
            if row:times.append(row[0])
        outputs={self.path(config['output_dir'])}
        for job in jobs:
            times.append(job['updated'])
            snapshot=read(self.path(job['config']))
            if snapshot:outputs.add(self.path(snapshot['output_dir']))
        for output in outputs:
            for name in ('corrections.json','review_corrections.json','analysis_progress.json','level_progress.json','tracks.json','focused.mp4','comparison.mp4'):
                path=output/name
                if path.exists():times.append(path.stat().st_mtime)
        return max(times)

    def library(self, active_project=None):
        projects=[];jobs=self.jobs();discarded=self.discarded();archived=[]
        for path in sorted(self.root.glob('*.json')):
            try:
                c, labels, rev = self.inputs(path.name)
                prep = self.preparation(path.name)
                ready=bool(prep.get('ready') and prep.get('revision')==rev and prep.get('description','').strip() and c.get('reference_box'))
                revision=hashlib.sha256((rev+prep.get('description','')).encode()).hexdigest()
                related=[j for j in jobs if j['project']==path.name]
                updated_at=self.last_updated(path.name,c,prep,related)
                pending=next((j for j in reversed(related) if j['status'] in ('queued','starting','running')),None)
                if path.name==active_project:pending={'id':None,'config':path.name,'status':'running'}
                if path.name in discarded and not pending:
                    archived.append({'project':path.name,'video':c['video'],'updated_at':updated_at});continue
                completed=next((j for j in reversed(related) if j['status']=='succeeded' and j['revision']==revision),None)
                comparison=self.path(c['output_dir'])/'comparison.mp4'
                inputs_mtime=max(path.stat().st_mtime,(self.path(c['output_dir'])/'corrections.json').stat().st_mtime if (self.path(c['output_dir'])/'corrections.json').exists() else 0)
                legacy_done=not related and comparison.exists() and inputs_mtime<=comparison.stat().st_mtime and (not prep or (prep.get('approved_at') or float('inf'))<=comparison.stat().st_mtime)
                has_input=bool(c.get('reference_box') or labels or c.get('target','').strip() or prep.get('description','').strip())
                status='Processing' if pending else 'Done' if completed or legacy_done else 'Ready' if ready else 'Draft' if has_input else 'New'
                try:
                    self.rerender_source(path.name,jobs);can_rerender=not pending and path.name not in discarded
                except (ValueError,OSError,KeyError):can_rerender=False
                actions=['Label subject','Review descriptions']
                if can_rerender:actions.append('Queue Rerendering (no re-analysis)')
                if status=='Ready':actions.append('Queue processing')
                if status in ('Processing','Done'):actions.append('Open video focus')
                if status=='Done':actions.append('Watch side by side')
                actions.append('Discard project')
                projects.append(dict(project=path.name,updated_at=updated_at,status=status,actions=actions,discard_pending=path.name in discarded,
                    can_rerender=can_rerender,active_job=pending['id'] if pending else None,active_config=pending['config'] if pending else None,completed_config=completed['config'] if completed else path.name if legacy_done else None,
                    latest_job=pending['status'] if pending else related[-1]['status'] if related else None,
                    has_box=bool(c.get('reference_box')),video=c['video'],target=c['target'],
                    reference_time=c.get('reference_time',0),reference_box=c['reference_box'],
                    labels=len(labels),description=prep.get('description',''),
                    ready=ready,
                    stale=bool(prep.get('ready') and prep.get('revision')!=rev),
                    analysis_fps=c.get('analysis_fps'),tracking_mode=c.get('tracking_mode','single')))
            except (ValueError,OSError,TypeError,KeyError):
                continue
        videos=[str(p.relative_to(self.root)) for p in sorted(self.root.iterdir()) if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in VIDEO_SUFFIXES]
        jobs=self.jobs()
        for job in jobs:
            c=read(self.path(job['config']));out=self.path(c['output_dir'])
            job['stage']=c.get('batch_stage','all')
            job['progress']=({'stage':'render','completed':None,'total':None} if job['stage']=='render' else read(out/'analysis_progress.json',{}))
            from tracking_progress import progress_for_ui
            job['progress']=progress_for_ui(out,c,job['progress'])
            flags=read(out/'review_flags.json',[])
            job['review_count']=len(flags) if isinstance(flags,(list,dict)) else 0
            job['comparison_available']=(out/'comparison.mp4').exists()
            job['output_dir']=str(out.relative_to(self.root))
            job['pending_corrections']=(out/'review_corrections.json').exists()
        return dict(projects=projects,archived=archived,videos=videos,jobs=[j for j in jobs if j['project'] not in discarded or j['status'] in ('starting','running')],paused=self.paused())

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
            if project in self.discarded():raise ValueError('Restore discarded projects before queuing')
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

    def rerender_source(self, project, jobs=None):
        """Find the latest completed analysis, falling back to legacy source output."""
        jobs=self.jobs() if jobs is None else jobs
        candidates=[j['config'] for j in reversed(jobs) if j['project']==project and j['status']=='succeeded']+[project]
        for name in candidates:
            c=read(self.path(name));out=self.path(c['output_dir'])
            c=read(out/'run_config.json',c)
            observations=f"tracking_{c.get('tracking_render_path','selected')}.json" if c.get('tracking_mode')=='dual' else 'observations.json'
            meta=read(out/'meta.json',{})
            if (out/observations).is_file() and meta.get('frames') and meta.get('cache'):
                reference=self.path(meta['cache'])/'reference.jpg'
                if reference.is_file():return name,out,observations,meta,reference
        raise ValueError(f'{project}: no saved analysis is available to rerender')

    def enqueue_rerender(self, projects):
        if not projects:raise ValueError('Select at least one project with saved analysis')
        prepared=[];jobs=self.jobs()
        for project in dict.fromkeys(projects):
            if project in self.discarded():raise ValueError('Restore discarded projects before queuing')
            if any(j['project']==project and j['status'] in ('queued','starting','running') for j in jobs):
                raise ValueError(f'{project}: a job is already queued or running')
            current,current_labels,rev=self.inputs(project);prep=self.preparation(project)
            source_name,source_out,observations,meta,reference=self.rerender_source(project,jobs)
            source_config=read(source_out/'run_config.json',read(self.path(source_name)))
            if self.path(source_config['video'])!=self.path(current['video']):
                raise ValueError('Video changed since the saved analysis; analyze the new video first')
            manifest=read(self.path(source_name).parent/'inputs.json',{}) if source_name!=project else {}
            stat=self.path(current['video']).stat();source_stat={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}
            if manifest and manifest.get('source_stat')!=source_stat:
                raise ValueError('Source video changed since analysis; analyze it again first')
            # Review-run corrections start from its frozen labels. Source edits
            # override only labels actually changed since that run was queued.
            labels=read(source_out/'review_corrections.json',read(source_out/'corrections.json',{}))
            baseline=manifest.get('source_labels',manifest.get('labels',{}))
            if source_name==project:labels=current_labels
            else:
                for frame in baseline.keys()|current_labels.keys():
                    if current_labels.get(frame)!=baseline.get(frame):
                        if frame in current_labels:labels[frame]=current_labels[frame]
                        else:labels.pop(frame,None)
            snapshot=dict(source_config)
            for key in ('output_width','output_height','subject_height_fraction','margin_fraction',
                        'hold_seconds','widen_seconds','smoothing_seconds','feather_pixels','border',
                        'tracking_selection','leveling_source','level_divergence_degrees'):
                if key in current:snapshot[key]=current[key]
            prepared.append((project,rev,prep,current,labels,source_name,source_out,observations,meta,reference,snapshot,source_stat))
        ids=[]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for project,rev,prep,current,labels,source_name,source_out,observations,meta,reference,snapshot,source_stat in prepared:
                if db.execute("SELECT 1 FROM jobs WHERE project=? AND status IN ('queued','starting','running')",(project,)).fetchone():
                    raise ValueError(f'{project}: a job is already queued or running')
                job_id=uuid.uuid4().hex;out=self.root/'outputs'/'batch'/job_id
                config_path=self.folder/'runs'/job_id/'project.json'
                out.mkdir(parents=True);cache=out/'cache';cache.mkdir()
                shutil.copy2(reference,cache/'reference.jpg')
                write(out/'meta.json',dict(meta,cache=str(cache)))
                for name in {observations,'observations.json','tracking_raw_angle.json','tracking_leveled.json',
                             'tracking_selected.json','tracking_comparison.json','level_observations.json'}:
                    if (source_out/name).is_file():shutil.copy2(source_out/name,out/name)
                revision=hashlib.sha256((rev+prep.get('description','')).encode()).hexdigest()
                snapshot.update(video=str(self.path(current['video'])),output_dir=str(out),batch_stage='render',
                                batch_input_revision=revision,rerender_source=source_name)
                write(config_path,snapshot);write(out/'corrections.json',labels)
                # Adoption compares against current source inputs, just like analysis jobs.
                preparation=dict(prep,revision=rev,description=prep.get('description',''))
                write(config_path.parent/'inputs.json',dict(project=project,revision=revision,preparation=preparation,
                    config=current,labels=labels,source_labels=current_labels,source_stat=source_stat,stage='render',analysis_source=source_name))
                now=time.time();relative=str(config_path.relative_to(self.root))
                db.execute('INSERT INTO jobs (id,project,revision,status,created,updated,config,priority) VALUES (?,?,?,?,?,?,?,?)',
                           (job_id,project,revision,'queued',now,now,relative,1));ids.append(job_id)
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
            if row['project'] in self.discarded():raise ValueError('Restore the project before retrying')
            if action=='retry' and row['status'] in ('failed','interrupted'):
                manifest=read(self.path(row['config']).parent/'inputs.json')
                run=read(self.path(row['config']))
                if read(self.path(run['output_dir'])/'corrections.json',{})!=manifest['labels']:
                    raise ValueError('Labels changed: copy corrections to the source and queue a new revision instead of retrying old inputs')
                db.execute("UPDATE jobs SET status='queued',error=NULL,updated=? WHERE id=?",(time.time(),job_id))
            elif action=='cancel' and row['status']=='queued':
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?",(time.time(),job_id))
            else:raise ValueError('Only queued jobs can be cancelled; failed/interrupted jobs can be retried')

    def stop(self,job_id):
        from job_control import runner_handles,terminate
        # Serialize against runner startup. Once interrupted, an unstarted runner exits.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job or job['status'] not in ('starting','running'):
                raise ValueError('Only starting or running jobs can be stopped')
            handles=runner_handles(self.root,job_id,Path(__file__).resolve())
            try:
                if handles:terminate(handles)
                for attempt in range(40):
                    with file_lock(self.folder/'locks'/(job_id+'.lock')) as acquired:
                        if acquired:
                            db.execute("UPDATE jobs SET status='interrupted',error=?,updated=? WHERE id=?",
                                ('Stopped by user; Retry saved inputs resumes compatible cached work.',time.time(),job_id))
                            break
                    time.sleep(.05)
                else:raise RuntimeError('Runner has not stopped yet; try Stop processing again')
            finally:
                for _,fd in handles:os.close(fd)
        return {'stopped':job_id,'status':'interrupted'}

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
                    row=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC, created LIMIT 1").fetchone()
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
                            stage=c.get('batch_stage','all')
                            if stage not in ('all','render'):raise ValueError('Invalid batch stage')
                            sys.argv=[str(SOURCE/'reframe.py'),str(config),'--stage',stage]
                            runpy.run_path(str(SOURCE/'reframe.py'),run_name='__main__')
                        code=0
                if code:raise RuntimeError(f'Processor exited with code {code}; see job log')
                status,error='succeeded',None
            except BaseException as exc:
                status,error='failed',f'{type(exc).__name__}: {exc}'
            with self.db() as db:db.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE id=?',(status,error,time.time(),job_id))


def draft_description(batch, project):
    from description_review import review
    return review(batch,project,'draft')['description']


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--execute')
    args=parser.parse_args();batch=Batch(args.workspace)
    if args.worker:batch.worker()
    elif args.execute:batch.execute(args.execute)
