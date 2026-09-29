"""Four independent candidate records, with shared seed/render selection rules."""
import json
from pathlib import Path
from functools import lru_cache
from verification_policy import accepted_row
from motion_render import motion_usable

PATHS=('raw_angle','leveled')


def choose(candidates,threshold=.5,previous=None,seed=False):
    available=[r for r in candidates if r and r.get('bbox') and not r.get('error') and not r.get('scene_cut')]
    manual=next((r for r in candidates if r and r.get('manual')),None)
    if manual:return manual
    # Measured and inherited identity scores remain distinct in provenance.
    valid=[r for r in available if accepted_row(r,threshold) or motion_usable(r)]
    if not valid:return None
    return max(valid,key=lambda r:(r.get('confidence',0),r.get('candidate_id')==previous))


def combine(previous,candidate,threshold=.5):
    if previous and previous.get('manual'):return previous
    records=dict((previous or {}).get('four_candidates',{}))
    for key,value in candidate.get('four_candidates',{}).items():
        old=records.get(key)
        # A failed discovery cannot erase usable motion or a stronger proposal.
        if old is None or not old.get('bbox') or value.get('bbox') and value.get('confidence',0)>=old.get('confidence',0):records[key]=value
    winners={path:choose([v for v in records.values() if v.get('path')==path],threshold,
                        (previous or {}).get('path_results',{}).get(path,{}).get('candidate_id')) for path in PATHS}
    winner=choose(list(records.values()),threshold,(previous or {}).get('candidate_id'))
    base=dict(winner or candidate)
    base.update(four_candidates=records,path_results={k:v for k,v in winners.items() if v},
        candidates={p:winners[p] or dict(frame=candidate['frame'],bbox=None,confidence=0,visibility='uncertain') for p in PATHS},
        analysis_failures=candidate.get('analysis_failures',[]))
    base['selected_path']=winner.get('path') if winner else 'neither'
    base['selection_reason']='Highest crop identity confidence; reliable optical fallback if no candidate passes verification'
    return base


def record(folder,frame,candidates):
    path=Path(folder)/'path_candidates.jsonl'
    with path.open('a') as stream:stream.write(json.dumps(dict(frame=frame,candidates=candidates),allow_nan=False)+'\n')


@lru_cache(maxsize=4)
def _load(path,mtime,size):
    result={}
    with open(path) as stream:
        for line in stream:
            try:row=json.loads(line)
            except ValueError:continue
            target=result.setdefault(str(row['frame']),{})
            for key,value in row['candidates'].items():
                old=target.get(key)
                if old is None or not old.get('bbox') or value.get('bbox') and value.get('confidence',0)>=old.get('confidence',0):target[key]=value
    return result


def load(folder):
    path=Path(folder)/'path_candidates.jsonl'
    if not path.exists():return {}
    stat=path.stat();return _load(str(path),stat.st_mtime_ns,stat.st_size)


def apply_to_render(observations,folder,threshold):
    rows={r['frame']:r for r in observations}
    previous=None
    for frame,candidates in sorted(load(folder).items(),key=lambda p:int(p[0])):
        i=int(frame)
        if rows.get(i,{}).get('manual'):continue
        winner=choose(list(candidates.values()),threshold,previous)
        if winner:
            rows[i]=dict(winner,selected_path=winner['path'],selection_reason='Highest crop identity confidence across four saved candidates',four_candidates=candidates)
            previous=winner.get('candidate_id')
    return [rows[i] for i in sorted(rows)]
