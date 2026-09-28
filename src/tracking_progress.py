"""Independent coverage and attempt counts for adaptive tracking's three timescales."""
import json
import threading
import time
from pathlib import Path
import numpy as np


def discovery_grid(start,stop,fps,rate):
    return sorted(i for i in set(int(round(t*fps)) for t in np.arange(start/fps,(stop+.1)/fps,1/rate))|{stop} if start<=i<=stop)


def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,allow_nan=False));temp.replace(path)


class TrackingProgress:
    def __init__(self,out,fingerprint,discovery,checkpoints,start,stop,threshold,resuming=False):
        self.out=Path(out);self.path=self.out/'tracking_work.jsonl'
        self.discovery=set(discovery);self.checkpoints=set(checkpoints);self.start=start;self.stop=stop
        self.threshold=threshold;self.lock=threading.RLock();self.state=None;self.last_write=0
        self.frames={'discovery':{},'verification':{},'optical':{}}
        self.attempts={k:dict(total=0,accepted=0,rejected=0,errored=0,cached=0) for k in self.frames}
        self.incomplete=bool(resuming)
        matching=False
        if self.path.exists():
            with self.path.open() as stream:
                try:header=json.loads(next(stream))
                except (ValueError,StopIteration):header={}
                matching=header.get('fingerprint')==fingerprint
                if matching:
                    self.incomplete=header.get('historical_incomplete',False)
                    for line in stream:
                        try:self._apply(json.loads(line))
                        except (ValueError,KeyError):self.incomplete=True
        if matching:
            with self.path.open('rb') as stream:
                stream.seek(-1,2);ends_with_newline=stream.read(1)==b'\n'
            if not ends_with_newline:
                with self.path.open('a') as stream:stream.write('\n')
        if not matching:
            self.path.write_text(json.dumps({'fingerprint':fingerprint,'historical_incomplete':self.incomplete})+'\n')

    def _apply(self,event):
        kind=event['kind'];frame=str(event['frame']);outcome=event['outcome']
        counts=self.attempts[kind]
        if event.get('cached'):counts['cached']+=1
        else:counts['total']+=1;counts[outcome]+=1
        paths=self.frames[kind].setdefault(frame,{})
        # Latest result per path/branch; any successful optical visit makes the frame usable.
        path=event.get('path','')
        if kind=='optical' and paths.get(path)=='accepted':return
        paths[path]=outcome

    def record(self,kind,frame,outcome,path='',cached=False):
        if not self.start<=frame<=self.stop:return
        event=dict(kind=kind,frame=frame,outcome=outcome,path=path,cached=cached)
        with self.lock:
            with self.path.open('a') as stream:stream.write(json.dumps(event)+'\n')
            self._apply(event)
            if self.state is not None and time.monotonic()-self.last_write>=1:self.publish(self.state)

    def verification(self,frame,result,path,cached=False):
        comparison=result.get('comparison',{})
        outcome='errored' if result.get('error') else 'accepted' if (
            comparison.get('target_present') and comparison.get('match_score',0)>=self.threshold
            and comparison.get('target_complete') is True) else 'rejected'
        self.record('verification',frame,outcome,path,cached or result.get('cache_hit',False))

    def publish(self,state):
        with self.lock:
            self.state=state
            groups={}
            for kind,positions in self.frames.items():
                allowed=self.discovery if kind=='discovery' else self.checkpoints if kind=='verification' else None
                selected={int(f):p for f,p in positions.items() if allowed is None or int(f) in allowed}
                counts=dict(accepted=0,rejected=0,errored=0)
                for paths in selected.values():
                    outcomes=paths.values()
                    category='accepted' if 'accepted' in outcomes else 'rejected' if 'rejected' in outcomes else 'errored'
                    counts[category]+=1
                groups[kind]=dict(examined=len(selected),total=len(allowed) if allowed is not None else self.stop-self.start+1,
                    **counts,attempts=dict(self.attempts[kind]),off_grid_examined=len(positions)-len(selected),available=True)
            scanned=set(map(int,self.frames['discovery']))
            coverage=state.get('coverage',{})
            resolved=sum(i not in scanned and (coverage.get(str(i),{}).get('manual') or coverage.get(str(i),{}).get('reliably_covered',False)) for i in self.discovery)
            groups['discovery'].update(resolved_without_scan=resolved,
                remaining=max(0,len(self.discovery)-groups['discovery']['examined']-resolved))
            result=dict(version=1,stage=state.get('stage'),anchors=len(state.get('anchors',[])),
                        pending_propagation=len(state.get('queue',[])),historical_incomplete=self.incomplete,**groups)
            save(self.out/'coverage_progress.json',result);self.last_write=time.monotonic()
            return result


def progress_for_ui(out,config,progress):
    """Old active processes can expose discovery coverage, but not invented flow counts."""
    if not progress or not progress.get('stage','').startswith('anchor_'):return progress
    out=Path(out);latest=out/'coverage_progress.json'
    if latest.exists():return dict(progress,coverage=json.loads(latest.read_text()))
    summary_path=out/'anchor_summary.json';meta_path=out/'meta.json'
    if not summary_path.exists() or not meta_path.exists():return progress
    summary=json.loads(summary_path.read_text());meta=json.loads(meta_path.read_text())
    start,stop=summary.get('analysis_interval',[0,meta['frames']-1])
    grid=discovery_grid(start,stop,meta['fps'],progress.get('discovery_fps',2))
    coverage=summary.get('coverage',{})
    scanned=sum(bool(coverage.get(str(i),{}).get('independent_scanned')) for i in grid)
    resolved=sum(not coverage.get(str(i),{}).get('independent_scanned') and bool(coverage.get(str(i),{}).get('manual') or coverage.get(str(i),{}).get('reliably_covered')) for i in grid)
    return dict(progress,source_fps=meta['fps'],coverage=dict(version=1,legacy=True,stage=summary.get('stage'),anchors=progress.get('anchors',0),
        pending_propagation=progress.get('queued',0),historical_incomplete=True,
        discovery=dict(available=True,examined=scanned,total=len(grid),resolved_without_scan=resolved,remaining=len(grid)-scanned-resolved),
        verification=dict(available=False,total=progress['total']),optical=dict(available=False,total=stop-start+1)))
