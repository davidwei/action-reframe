"""Recorded-trajectory replay, not an end-to-end accuracy evaluation.

Feature reinitialization means cross-checkpoint feature-count ratios are proxies,
not persistent feature survival. Historical model decisions are not ground truth.
Evaluates only existing measured checkpoint positions; no new model calls.
"""
import json,collections,copy,math
from pathlib import Path
import numpy as np
import argparse
parser=argparse.ArgumentParser(description="Replay adaptive verification scheduling on a frozen two-path run snapshot; never calls Qwen or changes production settings.")
parser.add_argument('snapshot',type=Path,help='Directory with meta, corrections, stage_store, stage_usage, optical_motion and path_candidates files')
root=parser.parse_args().snapshot
def rows(name):return [json.loads(l) for l in (root/name).read_text().splitlines()]
meta=json.loads((root/'meta.json').read_text());fps=meta['fps'];labels=json.loads((root/'corrections.json').read_text())
usage=[r for r in rows('stage_usage.jsonl') if r['stage']=='optical_tracking'];motions=rows('optical_motion.jsonl')
store=Path(json.loads((root/'stage_store.json').read_text())['root'])
candidates=collections.defaultdict(collections.deque)
rejections=[]
for r in rows('path_candidates.jsonl'):
 for c in r['candidates'].values():
  if c.get('candidate_id','').endswith('_optical') and c.get('confidence_measurement')=='measured':
   key=(c['frame'],c['path'],c['source_frame'],c['direction']);candidates[key].append(c)
   if not c.get('identity_verified'):rejections.append(c)
data=[]
for u,m in zip(usage,motions):
 key=u['key'];r=json.loads((store/'optical_tracking'/key[:2]/key/'record.json').read_text());o=r['result'];i=r['inputs'];v=o['motion']
 assert v['reliable']==m['reliable'] and v['feature_count']==m['feature_count'] and abs(v['motion_quality']-m['motion_quality'])<1e-8
 assert abs(v['uncertainty_px']-m['uncertainty_px'])<1e-8
 if v['reliable']:assert np.allclose(v['box'],m['bbox_px']) or m['path']=='leveled'
 key=(m['frame'],m['path'],m['source_frame'],m['direction']);c=candidates[key].popleft() if candidates[key] else None
 e=max(0,o['uncertainty']-i['uncertainty']-.15) if v['reliable'] else None
 prev=np.array(i['corners']);cur=np.array(o['corners']);scale=float(np.linalg.norm(cur[1]-cur[0])/np.linalg.norm(prev[1]-prev[0])) if v['reliable'] else None
 data.append(dict(m,e=e,scale=scale,seed_n=len(i['points'] or []),candidate=c))
assert not any(candidates.values()),'Snapshot mismatched checkpoint/motion counts'

def evaluate(interval, require_isolated=False):
 states={};pending={};counts=collections.Counter();rejected=[];delay=[];perclip=collections.defaultdict(collections.Counter)
 # Process in original execution order, retaining branch/direction frame history.
 for m in data:
  f=m['frame'];step=1 if m['direction']=='forward' else -1;branch=(m['path'],m['direction']);key=(*branch,f)
  prev=states.get((*branch,f-step))
  if f-step==m['source_frame'] and str(m['source_frame']) in labels:
   prev=dict(last_pass=m['source_frame'],last_attempt=m['source_frame'],baseline=m['seed_n'],points=[],pending_bad=None,trusted=True)
  if prev is None:prev=dict(last_pass=None,last_attempt=None,baseline=m['seed_n'],points=[],pending_bad=None,trusted=False)
  st=copy.deepcopy(prev);n=m['feature_count'];q=m['motion_quality'];e=m['e'];ratio=n/max(1,st['baseline'])
  box=m['bbox_px'];center=np.array([(box[0]+box[2])/2,(box[1]+box[3])/2]) if box else None
  hist=st['points'];window=max(1,round(fps*.1));past=next((a for a in reversed(hist) if abs(f-a['frame'])>=window),None)
  scale100=math.prod(a['scale'] for a in hist if past and abs(a['frame']-f)<abs(past['frame']-f))*(m['scale'] or 1)
  jump=float(np.linalg.norm(center-np.array(past['center']))/max(1,past['diagonal'])) if center is not None and past else 0
  abrupt=bool(past and (not .9<=scale100<=1.1 or jump>.25))
  strong=m['reliable'] and q>=.7 and n>=12 and ratio>=.5 and e<=.75 and not abrupt
  weak=m['reliable'] and (q<.5 or n<8 or ratio<.3 or e>1.)
  age=abs(f-st['last_pass'])/fps if st['last_pass'] is not None else float('inf')
  elapsed=abs(f-st['last_attempt'])/fps if st['last_attempt'] is not None else float('inf')
  st['urgent']=st.get('urgent',False) or abrupt or weak
  request=(require_isolated and not st['trusted']) or st['urgent'] or age>=(interval if strong else .25)
  c=m['candidate'];check=bool(c and request and elapsed>=.1-1e-6)
  if c:
   clip=f'{int(f/fps//10)*10:02d}-{int(f/fps//10)*10+10:02d}s'
   counts['available']+=1;perclip[clip]['available']+=1
   if check:counts['selected']+=1;perclip[clip]['selected']+=1
   good=c.get('identity_verified',False)
   if not good:
    counts['rejected']+=1;counts['rejected_selected' if check else 'rejected_skipped']+=1
    rejected.append(dict(frame=f,path=m['path'],direction=m['direction'],selected=check,age=age,q=q,n=n,r=ratio,e=e,scale100=scale100,jump100=jump,crop=c['box_verification'].get('crop_path')))
    if st['pending_bad'] is None:st['pending_bad']=f
   if check:
    st['last_attempt']=f;st['urgent']=False
    v=c['box_verification'];st['trusted']=bool(good and v['description'].get('composition')=='isolated_subject' and v['comparison'].get('localization_support')=='supported')
    if st['pending_bad'] is not None:
     delay.append(dict(first_rejection=st['pending_bad'],checked_frame=f,delay_seconds=abs(f-st['pending_bad'])/fps,result='pass' if good else 'reject'));st['pending_bad']=None
    if good:st['last_pass']=f;st['baseline']=n
  if center is not None:
   hist.append(dict(frame=f,center=center.tolist(),diagonal=math.hypot(box[2]-box[0],box[3]-box[1]),scale=m['scale'] or 1))
  st['points']=[h for h in hist if abs(f-h['frame'])<=window+1];states[key]=st
 return dict(stable_interval=interval,require_isolated=require_isolated,counts=dict(counts),rejections=rejected,followup_checks=delay,clips={k:dict(v) for k,v in sorted(perclip.items())})
summary=dict(snapshot_frames=[min(m['frame'] for m in data),max(m['frame'] for m in data)],motion_attempts=len(data),measured_attempts=sum(bool(m['candidate']) for m in data),results=[evaluate(x) for x in (1.,.5,.25)]+[evaluate(x,True) for x in (1.,.5)])
(root/'evaluation.json').write_text(json.dumps(summary,indent=2))
for r in summary['results']:
 print('INTERVAL',r['stable_interval'],r['require_isolated'],r['counts'],'clips',r['clips'])
 print('REJECTS',[(a['frame'],a['path'],a['selected'],round(a['age'],2),round(a['e'],4),round(a['jump100'],3),round(a['scale100'],3)) for a in r['rejections']]);print('FOLLOWUP',r['followup_checks'])
print('Frames',summary['snapshot_frames'],'motion',len(data))
