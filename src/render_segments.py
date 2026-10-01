"""Resume paired focused/comparison encoding from validated immutable segments."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import av
import cv2
import numpy as np
from durable_json import write_json,checksum,sync_directory

VERSION=1


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def validate_video(path,frames,size):
    with av.open(str(path)) as container:
        stream=container.streams.video[0]
        if (stream.width,stream.height)!=tuple(size):raise ValueError(f'Wrong segment dimensions: {path}')
        count=sum(1 for _ in container.decode(stream))
        if count!=frames:raise ValueError(f'Incomplete segment {path}: {count}/{frames} frames')


def letterbox(frame):
    h,w=frame.shape[:2];scale=min(960/w,540/h)
    image=cv2.resize(frame,(round(w*scale),round(h*scale)))
    canvas=np.zeros((540,960,3),np.uint8);y=(540-image.shape[0])//2;x=(960-image.shape[1])//2
    canvas[y:y+image.shape[0],x:x+image.shape[1]]=image
    return canvas


class Segments:
    def __init__(self,c,meta,identity):
        self.c=c;self.meta=meta;self.out=Path(c['output_dir'])
        self.key=checksum(dict(version=VERSION,identity=identity,fps=meta['fps'],frames=meta['frames'],
            size=[c['output_width'],c['output_height']],feather=c['feather_pixels'],seconds=c.get('render_segment_seconds',30)))
        self.folder=self.out/'render_segments'/self.key;self.folder.mkdir(parents=True,exist_ok=True)
        seconds=c.get('render_segment_seconds',30)
        if isinstance(seconds,bool) or not np.isfinite(seconds) or seconds<=0:raise ValueError('render_segment_seconds must be finite and positive')
        self.length=max(1,round(meta['fps']*seconds))
        self.done=[];self.reused=0

    def paths(self,start):
        return {kind:self.folder/f'{start:09d}_{kind}.mp4' for kind in ('focused','comparison')}

    def ready(self,start,stop):
        marker=self.folder/f'{start:09d}.json'
        try:
            saved=json.loads(marker.read_text())
            if saved['start']!=start or saved['stop']!=stop:return False
            for kind,path in self.paths(start).items():
                if file_hash(path)!=saved['hashes'][kind]:return False
        except (OSError,ValueError,KeyError,TypeError):return False
        self.done.append(start);self.reused+=1;self.progress(stop,'encoding')
        return True

    def progress(self,stop,phase):
        write_json(self.out/'render_progress.json',dict(stage='render',phase=phase,completed=stop,total=self.meta['frames'],
            segments_completed=len(self.done),segments_reused=self.reused,segment_frames=self.length,key=self.key))

    def encode(self,start,stop,frames):
        """frames yields (original, processed) for exactly [start, stop)."""
        paths=self.paths(start);processes={};temps={}
        try:
            for kind,path in paths.items():
                size=(self.c['output_width'],self.c['output_height']) if kind=='focused' else (1920,540)
                temp=path.with_suffix('.encoding.mp4');temps[kind]=temp
                command=[self.c['ffmpeg'],'-y','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24',
                    '-s',f'{size[0]}x{size[1]}','-r',str(self.meta['fps']),'-i','pipe:0','-an',
                    '-c:v','libx264','-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p',str(temp)]
                processes[kind]=subprocess.Popen(command,stdin=subprocess.PIPE)
            count=0
            for original,processed in frames:
                processes['focused'].stdin.write(processed.tobytes())
                processes['comparison'].stdin.write(np.hstack((letterbox(original),letterbox(processed))).tobytes())
                count+=1
            if count!=stop-start:raise RuntimeError('Render segment did not receive every frame')
            for process in processes.values():process.stdin.close()
            for process in processes.values():
                if process.wait()!=0:raise RuntimeError('Segment encoder failed')
            for kind,temp in temps.items():
                size=(self.c['output_width'],self.c['output_height']) if kind=='focused' else (1920,540)
                validate_video(temp,count,size)
                with temp.open('rb') as stream:os.fsync(stream.fileno())
                os.replace(temp,paths[kind])
            sync_directory(self.folder)
            write_json(self.folder/f'{start:09d}.json',dict(start=start,stop=stop,hashes={k:file_hash(p) for k,p in paths.items()}))
            self.done.append(start);self.progress(stop,'encoding')
        finally:
            for process in processes.values():
                if process.poll() is None:process.terminate()
                if process.stdin and not process.stdin.closed:
                    try:process.stdin.close()
                    except BrokenPipeError:pass
                process.wait()

    def assemble(self,metadata_args):
        n=self.meta['frames'];self.progress(n,'assembling')
        for kind in ('focused','comparison'):
            listing=self.folder/f'{kind}.ffconcat'
            # Controlled numeric filenames are safe in the concat syntax.
            lines=['ffconcat version 1.0']
            for start in range(0,n,self.length):
                lines += [f"file '{self.paths(start)[kind].name}'",f'duration {min(self.length,n-start)/self.meta["fps"]:.17f}']
            listing.write_text('\n'.join(lines)+'\n')
            temp=self.out/f'{kind}.encoding.mp4'
            subprocess.run([self.c['ffmpeg'],'-y','-hide_banner','-loglevel','error','-f','concat','-safe','1','-i',str(listing),
                '-i',self.c['video'],'-map','0:v:0','-map','1:a?','-c','copy','-t',str(n/self.meta['fps']),
                *metadata_args,'-movflags','+faststart+use_metadata_tags',str(temp)],check=True)
            with av.open(str(temp)) as container:
                if container.streams.video[0].frames!=n:raise ValueError('Assembled video frame count mismatch')
            with temp.open('rb') as stream:os.fsync(stream.fileno())
            os.replace(temp,self.out/f'{kind}.mp4');sync_directory(self.out)
        self.progress(n,'complete')
