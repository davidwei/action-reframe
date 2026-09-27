"""Small, cached H.264/AAC preview clips for browser-incompatible source codecs."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import uuid
import imageio_ffmpeg

CLIP_SECONDS=20
_LOCK=threading.Lock()
_SLOTS=threading.Semaphore(1)
_JOBS={}


def encode(source, output, start):
    temp=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.tmp.mp4')
    try:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
            '-threads','2','-ss',str(start),'-i',str(source),'-t',str(CLIP_SECONDS),
            '-map','0:v:0','-map','0:a:0?','-vf',
            'scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=15,format=yuv420p',
            '-filter_threads','1','-c:v','libx264','-threads','2','-preset','ultrafast','-crf','25',
            '-c:a','aac','-b:a','96k','-movflags','+faststart',str(temp)],
            check=True,capture_output=True,timeout=120)
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)


def preview(root, source, seconds):
    import math
    seconds=float(seconds)
    if not math.isfinite(seconds) or seconds<0:raise ValueError('Invalid preview time')
    start=int(seconds//CLIP_SECONDS)*CLIP_SECONDS
    stat=source.stat()
    key=hashlib.sha256(json.dumps([1,str(source),stat.st_size,stat.st_mtime_ns,start]).encode()).hexdigest()[:24]
    folder=Path(root)/'.batch'/'previews';folder.mkdir(parents=True,exist_ok=True)
    output=folder/(key+'.mp4');identity=str(output)
    result={'start':start,'clip_seconds':CLIP_SECONDS}
    if output.exists():return dict(result,status='ready',url='/files/'+str(output.relative_to(root)))
    with _LOCK:
        if identity not in _JOBS:
            _JOBS[identity]='processing'
            def run():
                try:
                    with _SLOTS:encode(source,output,start)
                    with _LOCK:_JOBS.pop(identity,None)
                except Exception as error:
                    with _LOCK:_JOBS[identity]='Preview conversion failed: '+str(error)
            threading.Thread(target=run,daemon=True).start()
        status=_JOBS[identity]
    return dict(result,status='processing' if status=='processing' else 'error',error=None if status=='processing' else status)
