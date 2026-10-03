"""Timestamp-preserving source decoding with explicit frame-gap repair records."""

from dataclasses import dataclass
import fcntl
import json
import math
from pathlib import Path

import av

from durable_json import write_json

VERSION = 1


@dataclass
class FrameRead:
    index: int
    image: object
    repaired: bool = False
    replacement_frame: int | None = None
    strategy: str | None = None

    def repair(self):
        if not self.repaired:return None
        return dict(frame=self.index,replacement_frame=self.replacement_frame,strategy=self.strategy,
                    reason='source_frame_missing_or_not_decoded')


def repair_timeline(decoded, start, stop):
    """Turn sparse timestamped decoded frames into every CFR timeline position."""
    expected=int(start);stop=int(stop);previous=None;previous_index=None
    for index,image in decoded:
        index=int(index)
        if index < start:
            previous=image;previous_index=index;continue
        if index < expected:continue
        if index >= stop:
            if expected < stop:
                for missing in range(expected,stop):
                    use_previous=previous is not None and missing-previous_index<=index-missing
                    replacement,source,strategy=(previous,previous_index,'previous') if use_previous else (image,index,'next')
                    yield FrameRead(missing,replacement,True,source,strategy)
                expected=stop
            break
        if index > expected:
            for missing in range(expected,index):
                use_previous=previous is not None and missing-previous_index<=index-missing
                replacement,source,strategy=(previous,previous_index,'previous') if use_previous else (image,index,'next')
                yield FrameRead(missing,replacement,True,source,strategy)
        yield FrameRead(index,image)
        expected=index+1;previous=image;previous_index=index
    if expected < stop:
        if previous is None:raise RuntimeError(f'No decodable source frame for interval {start}:{stop}')
        for missing in range(expected,stop):yield FrameRead(missing,previous,True,previous_index,'previous')


def _decoded(video, meta, start):
    fps=float(meta['fps'])
    with av.open(str(video)) as container:
        stream=container.streams.video[0];stream.thread_type='AUTO';stream.codec_context.thread_count=4
        origin=float((stream.start_time or 0)*stream.time_base)
        if start:
            try:container.seek(int((start/fps+origin)/stream.time_base),stream=stream,backward=True)
            except (av.error.FFmpegError,ValueError):pass
        packets=iter(container.demux(stream));consecutive_errors=0
        while True:
            try:packet=next(packets)
            except StopIteration:break
            except av.error.FFmpegError:
                consecutive_errors+=1
                if consecutive_errors>1000:break
                continue
            try:frames=packet.decode();consecutive_errors=0
            except av.error.FFmpegError:continue
            for frame in frames:
                if frame.pts is None or getattr(frame,'is_corrupt',False):continue
                seconds=float(frame.pts*frame.time_base)-origin;index=round(seconds*fps)
                if not math.isfinite(seconds) or abs(seconds-index/fps)>.35/fps:continue
                yield index,frame.to_ndarray(format='bgr24')


def frames(video, meta, start=0, stop=None):
    stop=int(meta['frames'] if stop is None else stop);start=int(start)
    if not 0<=start<=stop<=int(meta['frames']):raise ValueError('Invalid source frame interval')
    return repair_timeline(_decoded(video,meta,start),start,stop)


def frame(video, meta, index):
    return next(iter(frames(video,meta,index,index+1)))


def record_repairs(output_dir, stage, repairs):
    repairs=[repair for repair in repairs if repair]
    if not repairs:return
    output=Path(output_dir);path=output/'source_frame_repairs.json';lock=output/'source_frame_repairs.lock'
    output.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            try:value=json.loads(path.read_text())
            except (OSError,ValueError,TypeError):value={'schema':'source-frame-repairs/v1','frames':{}}
            for repair in repairs:
                key=str(int(repair['frame']));entry=value['frames'].setdefault(key,{'frame':int(repair['frame']),'stages':{}})
                entry['stages'][stage]={k:v for k,v in repair.items() if k!='frame'}
            write_json(path,value)
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def repaired_frames(output_dir):
    path=Path(output_dir)/'source_frame_repairs.json'
    try:return {int(key) for key in json.loads(path.read_text()).get('frames',{})}
    except (OSError,ValueError,TypeError):return set()
