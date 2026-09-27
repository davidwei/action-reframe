#!/usr/bin/env python3
"""Local video selector, rectangle editor and review server (loopback only)."""
import argparse
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

SOURCE_ROOT=Path(__file__).resolve().parent
WEB_ROOT=SOURCE_ROOT/"web"
ROOT=Path(os.environ.get("LONGVIDEO_WORKSPACE",str(SOURCE_ROOT.parent/"data"))).expanduser().resolve()


def project_defaults():
    c=json.loads((SOURCE_ROOT.parent/'configs/defaults.json').read_text())
    c['api_url']=os.environ.get('QWEN_API_URL',c['api_url']).rstrip('/')
    return c


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


def local_path(value):
    p=(ROOT/value).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('Path must be within this video folder')
    return p


class Handler(BaseHTTPRequestHandler):
    def json_response(self,data,code=200):
        blob=json.dumps(data).encode()
        self.send_response(code);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)

    def do_GET(self):
        try:
            parsed=urlparse(self.path);q=parse_qs(parsed.query)
            config_name=select_project(q.get('config',[''])[0])
            if parsed.path=='/api/videos':
                return self.json_response([p.name for p in sorted(ROOT.iterdir()) if p.suffix.lower() in ('.mp4','.mov','.mkv','.avi') and not p.name.startswith('.')])
            if parsed.path=='/api/state':
                config=json.loads(local_path(config_name).read_text()) if config_name else dict(project_defaults(),video='',target='',reference_time=0,output_dir='outputs/unconfigured')
                out=local_path(config['output_dir'])
                state={'project':config_name,'config':config,'running':JOB is not None and JOB.poll() is None,
                       'exit_code':None if JOB is None else JOB.poll()}
                for name in ('meta','tracks','review_flags','corrections','observations','analysis_progress','level_observations','level_comparison','level_summary','level_progress'):
                    p=out/(name+'.json');state[name]=json.loads(p.read_text()) if p.exists() else None
                log=out/'job.log'
                state['log']=log.read_text()[-3000:] if log.exists() else ''
                state['preview']=str((out/'focused.mp4').relative_to(ROOT)) if (out/'focused.mp4').exists() else None
                state['comparison']=str((out/'comparison.mp4').relative_to(ROOT)) if (out/'comparison.mp4').exists() else None
                state['comparison_version']=(out/'comparison.mp4').stat().st_mtime_ns if state['comparison'] else None
                return self.json_response(state)
            if parsed.path=='/api/frame':
                video=local_path(q['video'][0]);i=int(q.get('frame',['0'])[0])
                cap=cv2.VideoCapture(str(video));cap.set(cv2.CAP_PROP_POS_FRAMES,max(0,i));ok,f=cap.read();cap.release()
                if not ok:raise ValueError('Cannot decode requested frame')
                ok,b=cv2.imencode('.jpg',f,[cv2.IMWRITE_JPEG_QUALITY,92])
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b.tobytes());return
            if parsed.path=='/api/info':
                cap=cv2.VideoCapture(str(local_path(q['video'][0])))
                info={'width':int(cap.get(3)),'height':int(cap.get(4)),'fps':cap.get(cv2.CAP_PROP_FPS),'frames':int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
                cap.release();return self.json_response(info)
            path=WEB_ROOT/('review.html' if parsed.path=='/' else 'compare.html') if parsed.path in ('/','/compare') else WEB_ROOT/'frame_analysis.js' if parsed.path in ('/files/frame_analysis.js','/frame_analysis.js') else local_path(unquote(parsed.path.removeprefix('/files/')))
            if parsed.path not in ('/','/compare') and not parsed.path.startswith('/files/'):
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
            self.json_response({'error':str(e)},400)

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
            config_name=select_project(data.get('config'))
            config_path=local_path(config_name) if config_name else None
            with LOCK:
                if JOB is not None and JOB.poll() is None:
                    raise ValueError('Wait for the current job to finish before changing this project')
                if self.path=='/api/create':
                    video=local_path(data['video'])
                    if not video.is_file():raise ValueError('Video does not exist')
                    c=project_defaults()
                    # Never overwrite an existing project or its observations.
                    import uuid
                    name='project_'+uuid.uuid4().hex[:8]
                    c.update(video=str(video.relative_to(ROOT)),output_dir='outputs/'+name,reference_time=float(data['time']),
                             reference_box=data['bbox'],target=str(data['target']),color_refinement=False)
                    write_json(ROOT/(name+'.json'),c)
                    return self.json_response({'config':name+'.json'})
                if config_path is None:raise ValueError('Create a project first')
                c=json.loads(config_path.read_text());out=local_path(c['output_dir']);out.mkdir(parents=True,exist_ok=True)
                if self.path=='/api/settings':
                    cap=cv2.VideoCapture(str(local_path(c['video'])));source_fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
                    rate=set_analysis_fps(c,data['analysis_fps'],source_fps)
                    c.pop('sample_interval',None);write_json(config_path,c)
                    return self.json_response({'analysis_fps':rate})
                if self.path=='/api/correct':
                    i=int(data['frame']);meta=json.loads((out/'meta.json').read_text())
                    if not 0<=i<meta['frames']:raise ValueError('Frame out of range')
                    p=out/'corrections.json';values=json.loads(p.read_text()) if p.exists() else {}
                    v=values.get(str(i),{})
                    if 'bbox' in data:
                        b=data['bbox']
                        if b is not None:
                            if len(b)!=4 or not (0<=b[0]<b[2]<=meta['width'] and 0<=b[1]<b[3]<=meta['height']):raise ValueError('Invalid rectangle')
                        v['bbox']=b
                    if 'roll' in data and c.get('leveling_source')=='gyro':
                        raise ValueError('Gyro is the final leveling source; manual roll overrides are disabled for this project')
                    if 'roll' in data:
                        r=float(data['roll'])
                        if not -90<=r<=90:raise ValueError('Roll must be between -90 and 90 degrees')
                        v['roll']=r
                    values[str(i)]=v;write_json(p,values)
                    return self.json_response({'saved':i})
                if self.path=='/api/run':
                    stage=data.get('stage','all')
                    if stage not in ('all','analyze','backward','level','level-render','render','compare'):raise ValueError('Invalid stage')
                    if 'analysis_fps' in data and stage in ('all','analyze'):
                        cap=cv2.VideoCapture(str(local_path(c['video'])));source_fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
                        set_analysis_fps(c,data['analysis_fps'],source_fps);c.pop('sample_interval',None);write_json(config_path,c)
                    if LOG is not None:LOG.close()
                    LOG=(out/'job.log').open('w')
                    JOB=subprocess.Popen([sys.executable,str(SOURCE_ROOT/'reframe.py'),str(config_path),'--stage',stage],cwd=ROOT,stdout=LOG,stderr=subprocess.STDOUT)
                    return self.json_response({'started':JOB.pid})
                self.json_response({'error':'Not found'},404)
        except Exception as e:
            self.json_response({'error':str(e)},400)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765)
    p.add_argument('--workspace',type=Path,help='Video/project directory; defaults to LONGVIDEO_WORKSPACE or repository data/')
    a=p.parse_args()
    if a.workspace:ROOT=a.workspace.expanduser().resolve()
    ROOT.mkdir(parents=True,exist_ok=True)
    print(f'Open http://127.0.0.1:{a.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
