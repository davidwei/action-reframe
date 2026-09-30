#!/usr/bin/env python3
"""Local video selector, rectangle editor and review server (loopback only)."""
import argparse
import base64
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlparse, parse_qs, unquote

import cv2
from reframe import write_json, set_analysis_fps
from tracking_selection import set_confidence_threshold

SOURCE_ROOT=Path(__file__).resolve().parent
WEB_ROOT=SOURCE_ROOT/"web"
ROOT=Path(os.environ.get("LONGVIDEO_WORKSPACE",str(SOURCE_ROOT.parent/"data"))).expanduser().resolve()


def project_defaults():
    c=json.loads((SOURCE_ROOT.parent/'configs/defaults.json').read_text())
    c['api_url']=os.environ.get('QWEN_API_URL',c['api_url']).rstrip('/')
    return c


def set_anchor_options(config,data):
    saved={}
    for key in ('zoom_seconds_per_doubling','zoom_smoothing_seconds'):
        if key in data:config[key]=data[key];saved[key]=data[key]
    from zoom_path import smoothing_settings
    smoothing_settings(config)
    if config.get('render_planner',{}).get('enabled',True):
        for key,planner_key in [('zoom_seconds_per_doubling','seconds_per_doubling'),('zoom_smoothing_seconds','zoom_seconds')]:
            if key in data:config.setdefault('render_planner',{})[planner_key]=data[key]
        from render_planner import settings as render_planner_settings
        render_planner_settings(config)
    if 'minimum_crop_short_side' in data:
        config['minimum_crop_short_side']=data['minimum_crop_short_side'];saved['minimum_crop_short_side']=data['minimum_crop_short_side']
    if 'adaptive_verification' in data:
        config['adaptive_verification']=dict(config.get('adaptive_verification',{}),**data['adaptive_verification'])
        saved['adaptive_verification']=config['adaptive_verification']
    from adaptive_verification import settings as adaptive_settings
    adaptive_settings(config)
    if 'leveling_source' in data:
        if data['leveling_source'] not in ('gyro','visual'):raise ValueError('Invalid leveling source')
        config['leveling_source']=data['leveling_source'];saved['leveling_source']=data['leveling_source']
    if 'tracking_mode' in data:
        if data['tracking_mode'] not in ('single','dual','anchor'):raise ValueError('Invalid tracking mode')
        config['tracking_mode']=data['tracking_mode'];saved['tracking_mode']=data['tracking_mode']
    for key in ('anchor_confidence','discovery_fps'):
        if key in data:
            config.setdefault('anchor_tracking',{})[key]=data[key];saved[key]=data[key]
    if saved or config.get('tracking_mode')=='anchor':
        from anchor_tracking import settings
        settings(config)
    return saved


def ensure_review_meta(config,out):
    path=out/'meta.json'
    if path.exists():return json.loads(path.read_text())
    cap=cv2.VideoCapture(str(local_path(config['video'])))
    meta=dict(width=int(cap.get(3)),height=int(cap.get(4)),fps=cap.get(5),frames=int(cap.get(7)),samples=[])
    cap.release()
    if min(meta['width'],meta['height'],meta['fps'],meta['frames'])<=0:raise ValueError('Cannot read source metadata')
    return meta


def review_geometry(config,out,index):
    from label_geometry import preview_geometry
    meta=ensure_review_meta(config,out)
    if not 0<=index<meta['frames']:raise ValueError('Frame out of range')
    track_path=out/'tracks.json';tracks=json.loads(track_path.read_text()) if track_path.exists() else []
    track=tracks[index] if index<len(tracks) else None
    level_path=out/'level_comparison.json';levels=json.loads(level_path.read_text()) if not track and level_path.exists() else []
    roll=levels[index].get('final_roll') if index<len(levels) else None
    if roll is None and not track and config.get('leveling_source')=='gyro':
        gyro_path=out/'gyro.json'
        if gyro_path.exists():
            rows=json.loads(gyro_path.read_text()).get('frames',[])
            if index<len(rows):roll=rows[index].get('roll')
    return meta,track,preview_geometry(config,meta,track,roll)


def select_project(name):
    if name:
        return name
    for path in sorted(ROOT.glob('*.json')):
        try:
            config=json.loads(path.read_text())
            if all(k in config for k in ('video','output_dir','reference_box','target')):
                return path.name
        except (ValueError,OSError,TypeError):
            continue
    return None


LOCK=threading.Lock()
JOB=None
LOG=None


def batch_active():
    if not (ROOT/'.batch'/'queue.sqlite3').exists():return False
    from batch_workflow import Batch
    batch=Batch(ROOT)
    return batch.active() or (not batch.paused() and any(j['status']=='queued' for j in batch.jobs()))


def legacy_project():
    if JOB is None or JOB.poll() is not None:return None
    args=getattr(JOB,'args',[])
    if not args:
        try:args=Path(f'/proc/{JOB.pid}/cmdline').read_bytes().decode().split('\0')
        except OSError:args=[]
    for value in args:
        if isinstance(value,str) and value.endswith('.json'):
            try:return str(local_path(value).relative_to(ROOT))
            except ValueError:pass
    return None


def project_running(config_name):
    """Lock only the source project or snapshot belonging to an active job."""
    if not config_name:return False
    target=local_path(config_name)
    legacy=legacy_project()
    if legacy and local_path(legacy)==target:return True
    if not (ROOT/'.batch'/'queue.sqlite3').exists():return False
    from batch_workflow import Batch
    return any(j['status'] in ('starting','running') and
               any(j.get(key) and local_path(j[key])==target for key in ('project','config'))
               for j in Batch(ROOT).jobs())


def local_path(value):
    p=(ROOT/value).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('Path must be within this video folder')
    return p


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # An interactive launcher can disappear while this server stays alive.
        # Logging must never prevent send_response() from sending HTTP headers.
        try:
            super().log_message(format, *args)
        except (OSError, ValueError):
            pass

    def json_response(self,data,code=200):
        blob=json.dumps(data).encode()
        self.send_response(code);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)

    def do_GET(self):
        try:
            parsed=urlparse(self.path);q=parse_qs(parsed.query)
            if parsed.path.startswith('/api/lookout/'):
                from lookout.http import get
                if get(self,ROOT,parsed.path,q):return
            config_name=None if q.get('new')==['1'] else select_project(q.get('config',[''])[0])
            if parsed.path=='/api/batch':
                from batch_workflow import Batch
                result=Batch(ROOT).library(active_project=legacy_project());result['legacy_running']=JOB is not None and JOB.poll() is None
                return self.json_response(result)
            if parsed.path=='/api/videos':
                return self.json_response([p.name for p in sorted(ROOT.iterdir()) if p.suffix.lower() in ('.mp4','.mov','.mkv','.avi') and not p.name.startswith('.')])
            if parsed.path=='/api/state':
                config=json.loads(local_path(config_name).read_text()) if config_name else dict(project_defaults(),video='',target='',reference_time=0,output_dir='outputs/unconfigured')
                out=local_path(config['output_dir'])
                if config.get('video'):config['video']=str(local_path(config['video']).relative_to(ROOT))
                state={'project':config_name,'config':config,'running':project_running(config_name),
                       'execution_busy':(JOB is not None and JOB.poll() is None) or batch_active(),
                       'exit_code':None if JOB is None else JOB.poll()}
                source_project=config_name
                if config_name and config.get('batch_input_revision'):
                    manifest=local_path(config_name).parent/'inputs.json'
                    if manifest.exists():source_project=json.loads(manifest.read_text()).get('project',config_name)
                state['project_name']=config.get('project_name') or (Path(source_project).stem if source_project else None)
                from configuration_review import report as configuration_report
                source_config=None
                if source_project and source_project!=config_name and local_path(source_project).exists():
                    source_config=json.loads(local_path(source_project).read_text())
                    from batch_workflow import Batch
                    preparation=Batch(ROOT).preparation(source_project)
                    if preparation.get('description'):source_config['approved_target_description']=preparation['description']
                state['configuration_review']=configuration_report(config,out,source_config)
                import fcntl
                from contextlib import nullcontext
                with ((out/'analysis_snapshot.lock').open('a') if out.exists() else nullcontext()) as snapshot_lock:
                    if snapshot_lock is not None:fcntl.flock(snapshot_lock,fcntl.LOCK_SH)
                    for name in ('meta','tracks','review_flags','corrections','observations','analysis_progress','level_observations','level_comparison','level_summary','level_progress','tracking_comparison','anchor_summary','analysis_failures','analysis_snapshot'):
                        p=out/(name+'.json');state[name]=json.loads(p.read_text()) if p.exists() else None
                from optical_diagnostics import load as load_optical
                state['optical_motion']=load_optical(out)
                from path_candidates import load as load_path_candidates
                state['path_candidates']=load_path_candidates(out)
                from tracking_progress import progress_for_ui
                state['analysis_progress']=progress_for_ui(out,config,state['analysis_progress'])
                if config.get('batch_input_revision') and (out/'review_corrections.json').exists():
                    state['corrections']=json.loads((out/'review_corrections.json').read_text())
                if config_name and state['meta'] is None:state['meta']=ensure_review_meta(config,out)
                log=out/'job.log'
                state['log']=log.read_text()[-3000:] if log.exists() else ''
                state['preview']=str((out/'focused.mp4').relative_to(ROOT)) if (out/'focused.mp4').exists() else None
                state['comparison']=str((out/'comparison.mp4').relative_to(ROOT)) if (out/'comparison.mp4').exists() else None
                state['comparison_version']=(out/'comparison.mp4').stat().st_mtime_ns if state['comparison'] else None
                return self.json_response(state)
            if parsed.path=='/api/review-frame':
                if not config_name:raise ValueError('Create a project first')
                config=json.loads(local_path(config_name).read_text());out=local_path(config['output_dir']);index=int(q['frame'][0])
                meta,track,geometry=review_geometry(config,out,index)
                cap=cv2.VideoCapture(str(local_path(config['video'])));cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,frame=cap.read();cap.release()
                if not ok:raise ValueError('Cannot decode source frame')
                import numpy as np
                from reframe import composite
                processed=composite(frame,np.asarray(geometry['source_to_view']), (geometry['width'],geometry['height']),config.get('feather_pixels',40),track.get('bbox') if track else None)
                ok,encoded=cv2.imencode('.jpg',processed,[cv2.IMWRITE_JPEG_QUALITY,92])
                if not ok:raise ValueError('Cannot encode processed preview')
                return self.json_response({'frame':index,'geometry':geometry,'image':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()})
            if parsed.path in ('/api/frame','/api/reference'):
                reference_config=json.loads(local_path(config_name).read_text()) if parsed.path=='/api/reference' else None
                video=local_path(reference_config['video'] if reference_config else q['video'][0]);i=int(q.get('frame',['0'])[0])
                cap=cv2.VideoCapture(str(video));cap.set(cv2.CAP_PROP_POS_FRAMES,max(0,round(reference_config['reference_time']*cap.get(5)) if reference_config else i));ok,f=cap.read();cap.release()
                if not ok:raise ValueError('Cannot decode requested frame')
                if reference_config:
                    x1,y1,x2,y2=map(round,reference_config['reference_box']);f=f[y1:y2,x1:x2]
                ok,b=cv2.imencode('.jpg',f,[cv2.IMWRITE_JPEG_QUALITY,92])
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b.tobytes());return
            if parsed.path=='/api/preview':
                from video_preview import preview
                return self.json_response(preview(ROOT,local_path(q['video'][0]),q.get('time',['0'])[0]))
            if parsed.path=='/api/info':
                cap=cv2.VideoCapture(str(local_path(q['video'][0])))
                info={'width':int(cap.get(3)),'height':int(cap.get(4)),'fps':cap.get(cv2.CAP_PROP_FPS),'frames':int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
                cap.release();return self.json_response(info)
            path=WEB_ROOT/({'/':'review.html','/compare':'compare.html','/library':'library.html','/lookout':'lookout.html'}[parsed.path]) if parsed.path in ('/','/compare','/library','/lookout') else WEB_ROOT/Path(parsed.path).name if parsed.path in ('/files/configuration_review.js','/files/frame_analysis.js','/frame_analysis.js','/files/description_review.js','/files/tracking_progress.js','/files/lookout.js') else local_path(unquote(parsed.path.removeprefix('/files/')))
            if parsed.path not in ('/','/compare','/library','/lookout') and not parsed.path.startswith('/files/'):
                return self.json_response({'error':'Not found'},404)
            if not path.is_file():return self.json_response({'error':'Not found'},404)
            size=path.stat().st_size;start=0;end=size-1;status=200
            byte_range=self.headers.get('Range')
            if byte_range and byte_range.startswith('bytes='):
                left,right=byte_range[6:].split('-',1)
                if left:
                    start=int(left);end=min(int(right) if right else end,end)
                else:start=max(0,size-int(right))
                if start>end or start>=size:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
                status=206
            self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(path)[0] or 'application/octet-stream')
            self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    b=f.read(min(1024*1024,remaining))
                    if not b:break
                    self.wfile.write(b);remaining-=len(b)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as e:
            from model_response import ModelResponseError
            if isinstance(e,ModelResponseError):
                self.json_response({'error':str(e),'model_error':e.details},504 if e.details.get('kind')=='timeout' else 502)
            else:self.json_response({'error':str(e)},400)

    def do_POST(self):
        global JOB,LOG
        # Reject cross-origin writes to this loopback service.
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':
            return self.json_response({'error':'Cross-origin writes are disabled'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>1024*1024:raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length))
            if self.path.startswith('/api/lookout/'):
                from lookout.http import post
                from lookout.events import configure
                configure(ROOT)
                return self.json_response(post(ROOT,self.path.rsplit('/',1)[-1],data))
            config_name=select_project(data.get('config'))
            config_path=local_path(config_name) if config_name else None
            if self.path in ('/api/batch/draft','/api/batch/description-status','/api/batch/check-description','/api/batch/retry-description'):
                from batch_workflow import Batch
                from description_review import review
                action={'draft':'draft','description-status':'status','check-description':'check','retry-description':'retry'}[self.path.rsplit('/',1)[-1]]
                return self.json_response(review(Batch(ROOT),data['project'],action,data.get('description')))
            with LOCK:
                if self.path.startswith('/api/batch/'):
                    from batch_workflow import Batch
                    batch=Batch(ROOT);action=self.path.rsplit('/',1)[-1]
                    if action=='create':return self.json_response(batch.create_project(data['video']))
                    if action=='discard':
                        result=batch.discard(data['project']);result['finishing']=result['finishing'] or legacy_project()==data['project'];return self.json_response(result)
                    if action=='restore':return self.json_response(batch.restore(data['project']))
                    if action=='description-history':
                        from description_history import history
                        return self.json_response(history(batch,data['project']))
                    if action=='prepare':return self.json_response(batch.prepare(data['project'],data.get('description',''),data.get('ready',False)))
                    if action=='queue-rerender':
                        if legacy_project() in data.get('projects',[]):raise ValueError('Wait for this project’s running analysis to finish before queuing a rerender')
                        return self.json_response({'jobs':batch.enqueue_rerender(data.get('projects',[]))})
                    if action=='queue':return self.json_response({'jobs':batch.enqueue(data.get('projects',[]))})
                    if action=='start':
                        if JOB is not None and JOB.poll() is None:raise ValueError('An existing single-video job is running. Prepare/queue videos now; start the batch when it finishes.')
                        batch.start();return self.json_response({'started':True})
                    if action=='stop':return self.json_response(batch.stop(data['id']))
                    if action=='pause':batch.pause();return self.json_response({'paused':True})
                    if action in ('retry','cancel'):batch.action(data['id'],action);return self.json_response({'saved':True})
                    if action=='adopt':return self.json_response(batch.adopt(data['id']))
                    raise ValueError('Unknown batch action')
                if self.path=='/api/settings' and project_running(config_name):
                    raise ValueError('Wait for this project’s running job to finish before changing its settings')
                if self.path=='/api/run' and ((JOB is not None and JOB.poll() is None) or batch_active()):
                    raise ValueError('Another job is active. Use the folder queue or wait before starting a direct run')
                if self.path=='/api/create':
                    video=local_path(data['video'])
                    if not video.is_file():raise ValueError('Video does not exist')
                    c=project_defaults()
                    # Never overwrite an existing project or its observations.
                    import uuid
                    name='project_'+uuid.uuid4().hex[:8]
                    c.update(video=str(video.relative_to(ROOT)),output_dir='outputs/'+name,reference_time=float(data['time']),
                             reference_box=data['bbox'],target=str(data['target']))
                    from batch_workflow import Batch
                    Batch(ROOT).validate(c)
                    write_json(ROOT/(name+'.json'),c)
                    return self.json_response({'config':name+'.json'})
                if config_path is None:raise ValueError('Create a project first')
                c=json.loads(config_path.read_text());out=local_path(c['output_dir']);out.mkdir(parents=True,exist_ok=True)
                if c.get('batch_input_revision') and self.path in ('/api/settings','/api/run'):
                    raise ValueError('This is a saved batch run. Use the library to copy corrections to its source project and queue a new revision.')
                if self.path=='/api/refresh-analysis-snapshot':
                    from result_shards import export_snapshot
                    return self.json_response(export_snapshot(out,write_json))
                if self.path=='/api/settings':
                    saved={}
                    if 'analysis_fps' in data:
                        cap=cv2.VideoCapture(str(local_path(c['video'])));source_fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
                        saved['analysis_fps']=set_analysis_fps(c,data['analysis_fps'],source_fps)
                        c.pop('sample_interval',None)
                    if 'confidence_threshold' in data:
                        saved['confidence_threshold']=set_confidence_threshold(c,data['confidence_threshold'])
                    saved.update(set_anchor_options(c,data))
                    if not saved:raise ValueError('No supported settings supplied')
                    write_json(config_path,c)
                    return self.json_response(saved)
                if self.path=='/api/correct':
                    i=int(data['frame']);meta=ensure_review_meta(c,out)
                    if not 0<=i<meta['frames']:raise ValueError('Frame out of range')
                    p=out/('review_corrections.json' if c.get('batch_input_revision') else 'corrections.json')
                    baseline=out/'corrections.json'
                    values=json.loads(p.read_text()) if p.exists() else json.loads(baseline.read_text()) if baseline.exists() else {}
                    v=values.get(str(i),{})
                    if any(k in data for k in ('polygon','approve_path','bbox')):
                        from label_geometry import canonical_label,box_polygon
                        _,_,geometry=review_geometry(c,out,i)
                        if data.get('view_signature') and data['view_signature']!=geometry['signature']:
                            raise ValueError('Preview changed; reload the frame before saving the selection')
                        if 'approve_path' in data:
                            selected_path=data['approve_path']
                            if selected_path not in ('raw_angle','leveled','optical'):raise ValueError('Invalid path')
                            # Approve the exact displayed source-space outline, regardless of identity score.
                            points=data.get('polygon')
                            if points is None and selected_path=='optical':
                                from optical_diagnostics import load as load_optical
                                prediction=load_optical(out).get(str(i))
                                if not prediction or not prediction.get('reliable') or not prediction.get('bbox_px'):
                                    raise ValueError('No optical prediction supplied for this frame')
                                points=box_polygon(prediction['bbox_px'])
                            if points is None:
                                comparisons=json.loads((out/'tracking_comparison.json').read_text())
                                row=next((r for r in comparisons if r['frame']==i),None)
                                candidate=row.get(selected_path) if row else None
                                if not candidate or not candidate.get('bbox'):raise ValueError('No candidate box supplied for this frame')
                                points=candidate.get('source_polygon_px') if selected_path=='raw_angle' else None
                                if not points:
                                    box=[v*(meta['height'] if j%2 else meta['width'])/1000 for j,v in enumerate(candidate['bbox'])]
                                    points=box_polygon(box)
                            label=canonical_label(points,'raw',geometry);label['approved_path']=selected_path
                            label['approval_estimate']=data.get('approval_estimate')
                        elif data.get('polygon') is not None:
                            label=canonical_label(data['polygon'],data.get('space','raw'),geometry)
                        elif data.get('bbox') is not None:
                            label=canonical_label(box_polygon(data['bbox']),'raw',geometry)
                        else:
                            label={'bbox':None,'source_polygon_px':None,'processed_polygon_px':None,'confidence_source':'human'}
                        for key in ('source_polygon_px','processed_polygon_px','selection_space','view_polygon_px','preview_geometry','approved_path','approval_estimate','confidence_source'):
                            v.pop(key,None)
                        v.update(label)
                    if 'roll' in data and c.get('leveling_source')=='gyro':
                        raise ValueError('Gyro is the final leveling source; manual roll overrides are disabled for this project')
                    if 'roll' in data:
                        r=float(data['roll'])
                        if not -90<=r<=90:raise ValueError('Roll must be between -90 and 90 degrees')
                        v['roll']=r
                    values[str(i)]=v;write_json(p,values)
                    if not c.get('reference_box') and v.get('bbox') and not c.get('batch_input_revision'):
                        c['reference_box']=v['bbox'];c['reference_time']=i/meta['fps'];write_json(config_path,c)
                    return self.json_response({'saved':i})
                if self.path=='/api/run':
                    stage=data.get('stage','all')
                    if stage not in ('all','analyze','backward','level','level-render','render','compare'):raise ValueError('Invalid stage')
                    if 'analysis_fps' in data and stage in ('all','analyze'):
                        cap=cv2.VideoCapture(str(local_path(c['video'])));source_fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
                        set_analysis_fps(c,data['analysis_fps'],source_fps);c.pop('sample_interval',None)
                    if 'confidence_threshold' in data:
                        set_confidence_threshold(c,data['confidence_threshold'])
                    set_anchor_options(c,data)
                    write_json(config_path,c)
                    if LOG is not None:LOG.close()
                    LOG=(out/'job.log').open('w')
                    JOB=subprocess.Popen([sys.executable,str(SOURCE_ROOT/'reframe.py'),str(config_path),'--stage',stage],cwd=ROOT,stdout=LOG,stderr=subprocess.STDOUT)
                    return self.json_response({'started':JOB.pid})
                self.json_response({'error':'Not found'},404)
        except Exception as e:
            from model_response import ModelResponseError
            if isinstance(e,ModelResponseError):
                self.json_response({'error':str(e),'model_error':e.details},504 if e.details.get('kind')=='timeout' else 502)
            else:self.json_response({'error':str(e)},400)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765)
    p.add_argument('--workspace',type=Path,help='Video/project directory; defaults to LONGVIDEO_WORKSPACE or repository data/')
    a=p.parse_args()
    if a.workspace:ROOT=a.workspace.expanduser().resolve()
    ROOT.mkdir(parents=True,exist_ok=True)
    print(f'Open http://127.0.0.1:{a.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
