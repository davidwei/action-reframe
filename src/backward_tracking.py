"""One reverse pass over uncertain intervals, anchored in later confirmed detections."""
import copy
import math


def confident(observation, threshold=.65):
    from verification_policy import accepted_row
    return accepted_row(observation,threshold)


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


def bidirectional_pass(observations, attempt, adjudicate, threshold=.65, agreement_iou=.35, progress=None):
    """Extend each reliable reverse chain through confident forward observations.

    Reverse motion history contains the reverse estimates, even when forward wins the
    output comparison. An unreliable reverse observation ends its chain; an earlier
    reliable forward observation can seed a new one. Inputs are never mutated.
    """
    from tracking_selection import overlap
    forward=copy.deepcopy(sorted(observations,key=lambda r:r['frame']))
    result=copy.deepcopy(forward);history=[]
    report={'mode':'bidirectional','threshold':threshold,'agreement_iou':agreement_iou,
            'attempted_samples':0,'recovered_samples':0,'improved_samples':0,
            'forward_kept_samples':0,'unresolved_samples':0,'chains':[]}
    def reliable(r):
        return confident(r,threshold) and not r.get('error') and not r.get('scene_cut',False)
    for index in range(len(forward)-1,-1,-1):
        current=forward[index]
        if current.get('manual'):
            if report['chains'] and report['chains'][-1]['stop_reason'] is None:
                report['chains'][-1]['stop_reason']='Explicit user label'
            result[index].update(direction_choice='manual',direction_reason='Preserve explicit user label')
            history=history+[copy.deepcopy(current)] if reliable(current) else []
            if history:report['chains'].append({'seed_frame':current['frame'],'attempted_frames':[],'stop_reason':None})
            continue
        if not history:
            result[index].update(direction_choice='forward' if reliable(current) else 'neither',
                                 direction_reason='Forward anchor for backward traversal' if reliable(current) else 'No later reliable backward anchor')
            if reliable(current):
                history=[copy.deepcopy(current)]
                report['chains'].append({'seed_frame':current['frame'],'attempted_frames':[],'stop_reason':None})
            continue
        seed=history[-1]
        evidence=attempt(copy.deepcopy(current),copy.deepcopy(seed),copy.deepcopy(history))
        evidence=dict(evidence,frame=current['frame'],time=current['time'])
        report['attempted_samples']+=1
        if not report['chains'] or report['chains'][-1]['stop_reason'] is not None:
            report['chains'].append({'seed_frame':seed['frame'],'attempted_frames':[],'stop_reason':None})
        chain=report['chains'][-1];chain['attempted_frames'].append(current['frame'])
        fgood,bgood=reliable(current),reliable(evidence)
        iou=overlap(current.get('bbox'),evidence.get('bbox')) if fgood and bgood else None
        flags=[];judgment=None
        if fgood and bgood and iou<agreement_iou:
            flags.append('tracking_direction_disagreement')
            try:judgment=adjudicate(copy.deepcopy(current),copy.deepcopy(evidence),copy.deepcopy(history))
            except Exception as error:judgment={'choice':'neither','confidence':0,'error':str(error)}
            score=judgment.get('confidence',0)
            valid=(judgment.get('choice') in ('forward','backward') and isinstance(score,(int,float))
                   and math.isfinite(score) and threshold<=score<=1 and not judgment.get('error'))
            choice=judgment['choice'] if valid else 'neither'
            reason='Direction adjudication: '+str(judgment.get('reason') or judgment.get('error') or 'unresolved')
            if choice=='neither':flags.append('tracking_direction_uncertain')
        elif bgood and (not fgood or evidence['confidence']>current['confidence']):
            choice='backward';reason='Backward has higher verified confidence' if fgood else 'Backward recovers uncertain forward tracking'
        elif fgood:
            choice='forward';reason=('Exact confidence tie; retain forward' if bgood and evidence['confidence']==current['confidence']
                                     else 'Forward has higher verified confidence' if bgood else 'Backward is unreliable; retain forward')
        else:
            choice='neither';reason='Neither direction is reliable';flags.append('tracking_direction_uncertain')
        chosen=copy.deepcopy(evidence if choice=='backward' else current)
        if choice=='neither':chosen.update(bbox=None,confidence=0,visibility='uncertain')
        if judgment and choice!='neither':chosen['confidence']=min(chosen['confidence'],judgment['confidence'])
        chosen.update(direction_choice=choice,direction_reason=reason,direction_flags=flags,
                      direction_comparison={'forward':copy.deepcopy(current),'backward':copy.deepcopy(evidence),
                                            'box_iou':iou,'adjudication':judgment},
                      backward_attempt={'seed_frame':seed['frame'],'accepted':choice=='backward',
                                        'reliable':bgood,'evidence':copy.deepcopy(evidence)})
        if choice=='backward':
            chosen['analysis_source']='backward';chosen['backward_recovered']=not fgood
            chosen['backward_improved']=fgood
            chosen['first_pass_tracking']=copy.deepcopy(current)
            report['improved_samples' if fgood else 'recovered_samples']+=1
        elif choice=='forward':report['forward_kept_samples']+=1
        else:report['unresolved_samples']+=1
        result[index]=chosen
        # Winning the output comparison is NOT required to continue a reliable chain.
        if bgood and not (judgment and choice=='neither'):
            history.append(copy.deepcopy(evidence))
        else:
            chain['stop_reason']='Unresolved direction disagreement' if bgood else 'Backward confidence/verification failed'
            history=[]
        if progress:progress(copy.deepcopy(report),copy.deepcopy(chosen))
    for chain in report['chains']:
        if chain['stop_reason'] is None:chain['stop_reason']='Reached beginning or explicit user label'
    return result,report
