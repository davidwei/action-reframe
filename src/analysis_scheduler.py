"""Resumable anchor expansion followed by discovery of unresolved sample intervals."""
from collections import deque
from tracking_evidence import reliable,resolve

VERSION=1

class AnchorScheduler:
    def __init__(self,frames,discovery_frames,anchors,propagate,discover,save,settings=None,checkpoint=None):
        self.frames=sorted(set(frames));self.positions={f:i for i,f in enumerate(self.frames)}
        self.discovery=set(discovery_frames);self.propagate=propagate;self.discover=discover;self.save=save
        self.settings=settings or {};self.threshold=self.settings.get('confidence_threshold',.5)
        self.high=self.settings.get('anchor_confidence',.85)
        self.limit=self.settings.get('max_propagation_attempts',4)
        self.state=checkpoint or dict(version=VERSION,results={},coverage={},queue=[],attempts={},events=[],anchors=[])
        self.queue=deque(self.state['queue'])
        if checkpoint is None:
            for row in anchors:
                row=dict(row,localized=True,origin_anchor=row['frame'],parent_frame=None,anchor_kind='human')
                key=str(row['frame']);self.state['results'][key]=row
                self.state['coverage'][key]={'manual':True,'reliably_covered':reliable(row,self.threshold)}
                if reliable(row,self.high):self._anchor(row)
        self._save('ready')

    def _save(self,stage):
        self.state['queue']=list(self.queue);self.state['stage']=stage;self.save(self.state)

    def _enqueue(self,row,direction):
        pos=self.positions[row['frame']]+direction
        if not 0<=pos<len(self.frames):return
        target=self.frames[pos];key=f"{row.get('origin_anchor',row['frame'])}:{row['frame']}:{target}"
        if key in self.state['attempts']:return
        self.queue.append(dict(source=row['frame'],target=target,direction=direction,origin=row.get('origin_anchor',row['frame']),key=key))

    def can_anchor(self,row):
        return (row.get('localized') and reliable(row,max(self.high,self.threshold))
                and (row.get('manual') or row.get('box_verification',{}).get('comparison',{}).get('target_complete') is True)
                and not row.get('conflict'))

    def _anchor(self,row):
        if row['frame'] in self.state['anchors']:return
        self.state['anchors'].append(row['frame'])
        self._enqueue(row,-1);self._enqueue(row,1)

    def run(self):
        while True:
            if self.queue:
                task=self.queue[0];target=task['target'];key=str(target)
                existing=self.state['results'].get(key)
                count=sum(t['target']==target for t in self.state['attempts'].values())
                source=self.state['results'].get(str(task['source']))
                if (task['key'] in self.state['attempts'] or count>=self.limit
                    or (existing and existing.get('manual')) or not reliable(source,self.threshold)):
                    self.queue.popleft();continue
                self._save('propagating')
                candidate=self.propagate(source,target,task['direction'],self.state['results'])
                if candidate.get('error'):raise RuntimeError(candidate['error'])
                candidate=dict(candidate,origin_anchor=source.get('origin_anchor',source['frame']),parent_frame=source['frame'])
                self.queue.popleft();self.state['attempts'][task['key']]=task
                chosen,conflict=resolve(existing,candidate,self.threshold,self.settings.get('agreement_iou',.35))
                self.state['results'][key]=chosen
                coverage=self.state['coverage'].setdefault(key,{})
                coverage.update(propagation_attempted=True,reliably_covered=reliable(chosen,self.threshold))
                self.state['events'].append(dict(kind='propagation',frame=target,direction=task['direction'],origin_anchor=candidate['origin_anchor'],candidate=candidate,conflict=conflict))
                if reliable(candidate,self.threshold) and not conflict:
                    if self.can_anchor(candidate):self._anchor(candidate)
                    # Keep propagation ancestry even when a verified localization is promoted.
                    self._enqueue(candidate,task['direction'])
                self._save('propagating')
                continue
            pending=[f for f in sorted(self.discovery) if not self.state['coverage'].get(str(f),{}).get('independent_scanned')
                     and not self.state['coverage'].get(str(f),{}).get('reliably_covered')
                     and not self.state['coverage'].get(str(f),{}).get('manual')]
            # A branch conflict at an off-grid sample also warrants full-frame discovery.
            pending+= [int(f) for f,r in self.state['results'].items() if r.get('conflict') and not self.state['coverage'].get(f,{}).get('independent_scanned')]
            if not pending:break
            index=min(pending);self._save('discovering')
            row=self.discover(index,self.state['results'])
            if row.get('error'):raise RuntimeError(row['error'])
            row=dict(row,origin_anchor=index,parent_frame=None,anchor_kind='discovery')
            self.state['results'][str(index)]=row
            self.state['coverage'].setdefault(str(index),{}).update(independent_scanned=True,reliably_covered=reliable(row,self.threshold))
            self.state['events'].append(dict(kind='discovery',frame=index,candidate=row))
            if self.can_anchor(row):self._anchor(row)
            self._save('discovering')
        self._save('complete')
        return [self.state['results'][k] for k in sorted(self.state['results'],key=int)]
