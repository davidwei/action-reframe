"""One reverse pass over uncertain intervals, anchored in later confirmed detections."""
import copy
import math


def confident(observation, threshold=.65):
    box=observation.get('bbox')
    score=observation.get('confidence')
    return (isinstance(box,(list,tuple)) and len(box)==4
            and all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1000 for v in box)
            and box[0]<box[2] and box[1]<box[3]
            and isinstance(score,(int,float)) and math.isfinite(score) and threshold<=score<=1
            and observation.get('visibility') in ('visible','partial'))


def uncertain_intervals(observations, threshold=.65):
    """Return [start,end) sample indices and a right-hand seed; trailing gaps have no seed."""
    intervals=[];start=None
    for i,r in enumerate(observations):
        if not confident(r,threshold):
            if start is None:start=i
        elif start is not None:
            intervals.append((start,i,i));start=None
    if start is not None:intervals.append((start,len(observations),None))
    return intervals


def backward_pass(observations, attempt, threshold=.65, with_history=False):
    """Attempt each gap once, newest to oldest; stop a chain as soon as evidence fails.

    `attempt(current, later_seed)` must return measured evidence, not an extrapolated box.
    Input records are never mutated. Successful evidence replaces tracking fields;
    confident new shoreline evidence may update leveling, retaining its original values.
    With with_history=True, the callback also receives all later observations.
    """
    result=copy.deepcopy(sorted(observations,key=lambda r:r['frame']))
    report={'threshold':threshold,'intervals':[],'attempted_samples':0,'recovered_samples':0}
    for start,end,seed_index in uncertain_intervals(result,threshold):
        entry={'start_frame':result[start]['frame'],'end_frame':result[end-1]['frame'],
               'seed_frame':None if seed_index is None else result[seed_index]['frame'],
               'attempted_frames':[],'recovered_frames':[],'stop_reason':None}
        report['intervals'].append(entry)
        if seed_index is None:
            entry['stop_reason']='No confident detection at the end of the interval';continue
        seed=result[seed_index]
        for index in range(end-1,start-1,-1):
            current=result[index]
            if current.get('manual'):
                entry['stop_reason']='Stopped at a manual absent/uncertain label';break
            history=copy.deepcopy([r for r in reversed(result) if r['frame']>current['frame']])
            evidence=attempt(copy.deepcopy(current),copy.deepcopy(seed),history) if with_history else attempt(copy.deepcopy(current),copy.deepcopy(seed))
            entry['attempted_frames'].append(current['frame']);report['attempted_samples']+=1
            accepted=confident(evidence,threshold) and not evidence.get('scene_cut',False) and not evidence.get('error')
            details={'seed_frame':seed['frame'],'interval_seed_frame':result[seed_index]['frame'],
                     'accepted':accepted,'evidence':evidence}
            current['backward_attempt']=details
            if not accepted:
                entry['stop_reason']=evidence.get('error') or evidence.get('note') or 'Insufficient tracking confidence'
                break
            current['first_pass_tracking']={k:copy.deepcopy(current.get(k)) for k in
                ('bbox','confidence','visibility','note','error','raw','recovery_note','recovery_raw','recovery_error','recovery_rejected')}
            current.update(bbox=evidence['bbox'],confidence=evidence['confidence'],visibility=evidence['visibility'],
                           note=evidence.get('note','Recovered by backward tracking'),analysis_source='backward',
                           backward_recovered=True)
            current['temporal_context']=copy.deepcopy(evidence.get('temporal_context'))
            shore=evidence.get('shoreline');level_score=evidence.get('level_confidence',0)
            if (isinstance(shore,list) and len(shore)==4 and all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1000 for v in shore)
                    and abs(shore[2]-shore[0])>=150 and isinstance(level_score,(int,float)) and math.isfinite(level_score)
                    and threshold<=level_score<=1):
                current['first_pass_level']={k:copy.deepcopy(current.get(k)) for k in ('shoreline','level_confidence','level_note')}
                current.update(shoreline=shore,level_confidence=level_score,level_note=evidence.get('level_note'),level_source='backward')
            # These describe superseded tracking attempts, not the successful backward measurement.
            for key in ('error','recovery_error','recovery_rejected','recovery_note','recovery_raw','recovered'):
                current.pop(key,None)
            seed=current
            entry['recovered_frames'].append(current['frame']);report['recovered_samples']+=1
        if entry['stop_reason'] is None:entry['stop_reason']='Reached the beginning of the uncertain interval'
    return result,report
