"""Find tracked/untracked render intervals and export processed selections."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import imageio_ffmpeg
from durable_json import write_json
from export_metadata import ffmpeg_metadata_args

VERSION=1


def array_items(path,chunk_size=1024*1024):
    """Stream a top-level JSON array without retaining a long video's rows."""
    decoder=json.JSONDecoder();buffer='';started=False;eof=False
    with Path(path).open() as stream:
        while True:
            if not eof and len(buffer)<chunk_size:
                chunk=stream.read(chunk_size)
                if chunk:buffer+=chunk
                else:eof=True
            buffer=buffer.lstrip()
            if not started:
                if not buffer:
                    if eof:raise ValueError('Empty JSON array')
                    continue
                if buffer[0]!='[':raise ValueError('Expected a JSON array')
                buffer=buffer[1:];started=True;continue
            buffer=buffer.lstrip()
            if buffer.startswith(','):buffer=buffer[1:].lstrip()
            if buffer.startswith(']'):return
            try:value,end=decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:raise ValueError('Incomplete JSON array')
                chunk=stream.read(chunk_size)
                if chunk:buffer+=chunk
                else:eof=True
                continue
            yield value;buffer=buffer[end:].lstrip()
            if buffer.startswith(','):buffer=buffer[1:]
            elif buffer.startswith(']'):return
            elif eof:raise ValueError('Invalid JSON array separator')


def valid_box(value):
    return isinstance(value,list) and len(value)==4 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in value) and value[2]>value[0] and value[3]>value[1]


def guides_framing(row):
    """True when saved target geometry, from any path, guided this frame."""
    return valid_box(row.get('bbox')) and row.get('selected_path')!='neither'


def source_path(root,value):
    root=Path(root).resolve();path=Path(value)
    path=(path if path.is_absolute() else root/path).resolve()
    if not path.is_relative_to(root):raise ValueError('Part source must remain in the video workspace')
    return path


def _finish(parts,start,stop,tracked,counts,fps):
    parts.append(dict(index=len(parts)+1,start_frame=start,end_frame=stop,frames=stop-start,
        start_seconds=start/fps,end_seconds=stop/fps,duration_seconds=(stop-start)/fps,
        tracked=tracked,sources=dict(sorted(counts.items()))))


def build_index(tracks,meta):
    fps=float(meta['fps']);total=int(meta['frames'])
    if not math.isfinite(fps) or fps<=0 or total<=0:raise ValueError('Invalid render metadata')
    parts=[];start=0;previous=None;counts={};seen=0
    for expected,row in enumerate(array_items(tracks)):
        if expected>=total:raise ValueError('Tracks contain more frames than render metadata')
        if int(row.get('frame',expected))!=expected:raise ValueError(f'Non-contiguous track frame at {expected}')
        tracked=guides_framing(row)
        if previous is None:previous=tracked
        elif tracked!=previous:
            _finish(parts,start,expected,previous,counts,fps);start=expected;previous=tracked;counts={}
        source=str(row.get('selected_path') or 'unspecified');counts[source]=counts.get(source,0)+1;seen=expected+1
    if seen!=total:raise ValueError(f'Tracks contain {seen}/{total} frames')
    _finish(parts,start,total,previous,counts,fps)
    return parts


def build_from_rows(rows,meta):
    """Build the manifest while rendering already has the final rows in memory."""
    fps=float(meta['fps']);total=int(meta['frames'])
    if not math.isfinite(fps) or fps<=0 or total<=0:raise ValueError('Invalid render metadata')
    if len(rows)!=total:raise ValueError(f'Tracks contain {len(rows)}/{total} frames')
    parts=[];start=0;previous=None;counts={}
    for expected,row in enumerate(rows):
        if int(row.get('frame',expected))!=expected:raise ValueError(f'Non-contiguous track frame at {expected}')
        tracked=guides_framing(row)
        if previous is None:previous=tracked
        elif tracked!=previous:
            _finish(parts,start,expected,previous,counts,fps);start=expected;previous=tracked;counts={}
        source=str(row.get('selected_path') or 'unspecified');counts[source]=counts.get(source,0)+1
    _finish(parts,start,total,previous,counts,fps)
    return parts


def save_manifest(output,meta,rows=None):
    """Save the cheap semantic split; video clips remain virtual until requested."""
    output=Path(output);tracks=output/'tracks.json';stat=tracks.stat()
    identity=dict(version=VERSION,size=stat.st_size,mtime_ns=stat.st_mtime_ns,
        frames=int(meta['frames']),fps=float(meta['fps']))
    parts=build_from_rows(rows,meta) if rows is not None else build_index(tracks,meta)
    write_json(output/'parts_index.json',dict(identity=identity,parts=parts))
    return parts


def index(root,config_path):
    root=Path(root).resolve();config_path=source_path(root,config_path);config=json.loads(config_path.read_text())
    out=source_path(root,config['output_dir']);tracks=out/'tracks.json';meta_path=out/'meta.json'
    focused=out/'focused.mp4';comparison=out/'comparison.mp4'
    for path in (tracks,meta_path,focused,comparison):
        if not path.is_file():raise ValueError(f'Missing completed render artifact: {path.name}')
    meta=json.loads(meta_path.read_text());stat=tracks.stat();cache=out/'parts_index.json'
    identity=dict(version=VERSION,size=stat.st_size,mtime_ns=stat.st_mtime_ns,frames=int(meta['frames']),fps=float(meta['fps']))
    try:
        saved=json.loads(cache.read_text())
        if saved.get('identity')==identity:parts=saved['parts']
        else:raise ValueError('stale')
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        parts=save_manifest(out,meta)
    source=source_path(root,config['video']);folder=out/'parts';folder.mkdir(parents=True,exist_ok=True)
    for part in parts:
        target=source.parent/f'{source.stem}_part{part["index"]}{source.suffix}'
        status_path=folder/f'part_{part["index"]:04d}.json'
        status={}
        try:status=json.loads(status_path.read_text())
        except (OSError,ValueError,TypeError):pass
        part['filename']=target.name;part['output']=str(target.relative_to(root));part['save_status']=status.get('status','not_saved')
        part['save_progress']=status.get('progress');part['save_error']=status.get('error')
        if part['save_status']=='done' and not target.is_file():part['save_status']='not_saved'
    project_name=config.get('project_name')
    inputs=config_path.parent/'inputs.json'
    if not project_name and inputs.is_file():
        try:project_name=Path(json.loads(inputs.read_text()).get('project','')).stem or None
        except (OSError,ValueError,TypeError,AttributeError,json.JSONDecodeError):pass
    return dict(project=str(config_path.relative_to(root)),project_name=project_name or config_path.stem,
        source=str(source.relative_to(root)),comparison=str(comparison.relative_to(root)),comparison_version=comparison.stat().st_mtime_ns,
        focused=str(focused.relative_to(root)),fps=float(meta['fps']),frames=int(meta['frames']),parts=parts)


def _status_path(root,config_path,part_index):
    config=json.loads(source_path(root,config_path).read_text());out=source_path(root,config['output_dir'])
    folder=out/'parts';folder.mkdir(parents=True,exist_ok=True)
    return folder/f'part_{part_index:04d}.json'


def queue_export(root,config_path,part_index):
    root=Path(root).resolve();info=index(root,config_path);part=next((p for p in info['parts'] if p['index']==part_index),None)
    if part is None:raise ValueError('Unknown part')
    status_path=_status_path(root,config_path,part_index)
    try:status=json.loads(status_path.read_text())
    except (OSError,ValueError,TypeError):status={}
    pid=status.get('pid')
    if status.get('status') in ('queued','running') and pid:
        try:os.kill(int(pid),0);return status
        except (OSError,ValueError):pass
    status=dict(status='queued',progress=0,part=part_index,output=part['output'],queued_at=time.time())
    write_json(status_path,status)
    log=(status_path.parent/'exports.log').open('a')
    try:
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--workspace',str(root),'--config',str(source_path(root,config_path)),'--part',str(part_index)],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    finally:log.close()
    status.update(pid=process.pid);write_json(status_path,status)
    return status


def export(root,config_path,part_index):
    root=Path(root).resolve();info=index(root,config_path);part=next((p for p in info['parts'] if p['index']==part_index),None)
    if part is None:raise ValueError('Unknown part')
    status_path=_status_path(root,config_path,part_index);target=source_path(root,part['output']);source=source_path(root,info['focused'])
    lock_path=root/'.batch'/'part-exports.lock';lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        started=time.time();status=dict(status='running',progress=0,part=part_index,output=part['output'],pid=os.getpid(),started_at=started)
        write_json(status_path,status)
        temp=target.with_name('.'+target.stem+'.'+uuid.uuid4().hex+'.saving'+target.suffix)
        duration=float(part['duration_seconds']);start=float(part['start_seconds'])
        original=source_path(root,info['source'])
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-ss',f'{start:.9f}','-i',str(source),
            '-t',f'{duration:.9f}','-map','0:v:0','-map','0:a:0?',*ffmpeg_metadata_args(original,start),'-c:v','libx264','-threads','4','-preset','fast','-crf','18',
            '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart+use_metadata_tags','-progress','pipe:1','-nostats',str(temp)]
        last=0
        try:
            with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) as process:
                for line in process.stdout:
                    key,_,value=line.strip().partition('=')
                    if key=='out_time_us':
                        try:progress=min(1,float(value)/1_000_000/duration)
                        except (ValueError,ZeroDivisionError):continue
                        if time.monotonic()-last>.75:status['progress']=progress;write_json(status_path,status);last=time.monotonic()
                code=process.wait()
            if code:raise RuntimeError(f'Video export failed with code {code}; see {status_path.parent/"exports.log"}')
            os.replace(temp,target)
            status.update(status='done',progress=1,finished_at=time.time(),size=target.stat().st_size,pid=None);write_json(status_path,status)
            return status
        except BaseException as error:
            temp.unlink(missing_ok=True);status.update(status='failed',error=f'{type(error).__name__}: {error}',finished_at=time.time(),pid=None);write_json(status_path,status);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--config',type=Path,required=True);parser.add_argument('--part',type=int,required=True)
    args=parser.parse_args();export(args.workspace,args.config,args.part)
