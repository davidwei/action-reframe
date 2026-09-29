"""Integration of anchor scheduling, flow proposals, Qwen search and existing output."""
import hashlib
import json
from pathlib import Path
import numpy as np
from analysis_scheduler import AnchorScheduler
from tracking_progress import TrackingProgress,discovery_grid
from tracking_evidence import reliable
from manual_tracking import manual_observations
from two_path_tracking import TwoPathSearch as TrackingSearch
from leveling import extract_gyro
from tracking_selection import confidence_threshold
from dual_tracking import VERSION as DETECTION_VERSION
from box_verification import VERSION as VERIFICATION_VERSION

VERSION=5
DEFAULTS=dict(discovery_fps=2.,anchor_confidence=.85,padding_fraction=.15,min_padding_px=8.,
              max_dimension_ratio=1.5,max_area_ratio=2.,max_propagation_attempts=4)


def settings(config):
    result=dict(DEFAULTS,**config.get('anchor_tracking',{}))
    for key,value in result.items():
        if key in ('start_time','end_time'):continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value):raise ValueError('Invalid anchor setting: '+key)
    if not 0<result['discovery_fps']<=60:raise ValueError('discovery_fps must be >0 and <=60')
    if not confidence_threshold(config)<=result['anchor_confidence']<=1:raise ValueError('anchor_confidence must be between acceptance threshold and 1')
    if min(result['padding_fraction'],result['min_padding_px'])<0 or min(result['max_dimension_ratio'],result['max_area_ratio'])<1:raise ValueError('Invalid relaxation settings')
    if not 1<=result['max_propagation_attempts']<=20 or int(result['max_propagation_attempts'])!=result['max_propagation_attempts']:raise ValueError('Invalid propagation attempt limit')
    result['discovery_fps']=min(2.,result['discovery_fps'])
    return result


def run_anchors(c,meta,model,helpers,api,single=None):
    config=dict(c,anchor_tracking=settings(c));options=config['anchor_tracking'];out=Path(c['output_dir']);save=helpers[2]
    start=max(0,round(options.get('start_time',0)*meta['fps']))
    stop=min(meta['frames']-1,round(options.get('end_time',(meta['frames']-1)/meta['fps'])*meta['fps']))
    if single is not None:stop=min(stop,round(single*meta['fps']))
    if stop<start:raise ValueError('Invalid anchor analysis interval')
    manual=manual_observations(c,meta)
    # Initial selection is an explicit user label too; corrections can override it.
    reference=round(c['reference_time']*meta['fps'])
    if reference not in manual:
        manual[reference]=dict(frame=reference,time=reference/meta['fps'],bbox=(np.asarray(c['reference_box'])/[meta['width'],meta['height'],meta['width'],meta['height']]*1000).tolist(),
                               confidence=1.,confidence_source='human',manual=True,visibility='visible',analysis_source='manual',direction='manual')
    discovery=discovery_grid(start,stop,meta['fps'],min(2.,options['discovery_fps']))
    indices=sorted(set(i for i in meta['samples'] if start<=i<=stop)|set(discovery)|{i for i in manual if start<=i<=stop})
    if c.get('leveling_source')!='gyro':
        raise ValueError('Two-path optical analysis requires gyro leveling. Set leveling_source to gyro in the source project and queue a new run; visual mode cannot silently substitute zero rotation.')
    gyro=extract_gyro(c['video'],meta);save(out/'gyro.json',gyro)
    from verification_policy import VERSION as POLICY_VERSION
    from crop_description import VERSION as DESCRIPTION_VERSION
    from description_comparison import VERSION as COMPARISON_VERSION
    fingerprint=hashlib.sha256(json.dumps([VERSION,DETECTION_VERSION,VERIFICATION_VERSION,POLICY_VERSION,DESCRIPTION_VERSION,COMPARISON_VERSION,model,meta['signature'],config,manual],sort_keys=True,default=str).encode()).hexdigest()[:24]
    checkpoint=out/'anchor_checkpoint.json';prior=None
    if checkpoint.exists():
        previous=json.loads(checkpoint.read_text())
        if previous.get('fingerprint')==fingerprint:prior=previous
    if prior is None:
        (out/'optical_motion.jsonl').write_text('')
        (out/'path_candidates.jsonl').write_text('')
    search=TrackingSearch(config,meta,gyro,model,helpers,api)
    progress=TrackingProgress(out,fingerprint,discovery,indices,start,stop,confidence_threshold(c),resuming=prior is not None,anchor_threshold=options['anchor_confidence'])
    search.progress=progress
    search.discovery=set(discovery)
    def discover(index,rows):
        try:row=search.localize(index,rows)
        except Exception:
            progress.record('discovery',index,'errored');raise
        from verification_policy import verification_decision
        decisions=[verification_decision(r['box_verification'],confidence_threshold(c)) for r in row.get('candidates',{}).values() if r.get('box_verification')]
        categories={d['category'] for d in decisions}
        category=('request_error' if row.get('error') else 'accepted' if reliable(row,confidence_threshold(c)) else
                  'localization_rejected' if 'localization_rejected' in categories or 'accepted' in categories else
                  'identity_rejected' if 'identity_rejected' in categories or not categories else 'request_error')
        progress.record('discovery',index,'errored' if category=='request_error' else 'accepted' if category=='accepted' else 'rejected',category=category)
        progress.detection('discovery',index,row)
        return row
    def publish(state):
        state['fingerprint']=fingerprint;save(checkpoint,state)
        save(out/'analysis_failures.json',[dict(frame=int(i),time=int(i)/meta['fps'],failures=items) for i,items in sorted(state.get('analysis_failures',{}).items(),key=lambda pair:int(pair[0]))])
        rows=[];pairs=[]
        for index in indices:
            row=state['results'].get(str(index),dict(frame=index,time=index/meta['fps'],bbox=None,confidence=0,visibility='uncertain',selection_reason='Not examined yet',selection_flags=['tracking_unexamined']))
            row=dict(row,selected_path=row.get('selected_path','manual' if row.get('manual') else 'neither'))
            rows.append(row)
            candidates=row.get('candidates')
            if candidates and all(p in candidates for p in ('raw_angle','leveled')):pairs.append(dict(frame=index,time=row['time'],raw_angle=candidates['raw_angle'],leveled=candidates['leveled'],selected={k:v for k,v in row.items() if k!='candidates'},box_iou=row.get('box_iou')))
        save(out/'observations.json',rows);save(out/'tracking_selected.json',rows);save(out/'tracking_comparison.json',pairs)
        for path in ('raw_angle','leveled'):
            save(out/f'tracking_{path}.json',[r if r.get('manual') else r.get('candidates',{}).get(path,dict(frame=r['frame'],time=r['time'],bbox=None,confidence=0,visibility='uncertain')) for r in rows])
        coverage=state['coverage'];counts=progress.publish(state)
        save(out/'analysis_progress.json',dict(stage='anchor_'+state['stage'],completed=len(coverage),total=len(indices),
            source_fps=meta['fps'],analysis_fps=c['analysis_fps'],discovery_fps=options['discovery_fps'],anchors=len(state['anchors']),
            independent_scanned=sum(bool(r.get('independent_scanned')) for r in coverage.values()),
            reliably_covered=sum(bool(r.get('reliably_covered')) for r in coverage.values()),queued=len(state['queue']),coverage=counts))
        save(out/'anchor_summary.json',dict(stage=state['stage'],anchors=state['anchors'],settings=options,coverage=coverage,
            unresolved_frames=[r['frame'] for r in rows if not r.get('bbox')],analysis_interval=[start,stop]))
        print(f"Anchor {state['stage']}: discovery {counts['discovery']['examined']}/{counts['discovery']['total']} scanned + {counts['discovery']['resolved_without_scan']} resolved without scan; crop verification {counts['verification']['examined']}/{counts['verification']['total']} checked; optical {counts['optical']['examined']}/{counts['optical']['total']} visited; {len(state['anchors'])} anchors; {len(state['queue'])} propagation tasks",flush=True)
    scheduler=AnchorScheduler(indices,discovery,[r for i,r in manual.items() if start<=i<=stop],search.propagate,
        discover,publish,dict(options,two_path_tracking=True,confidence_threshold=confidence_threshold(c),agreement_iou=c.get('tracking_selection',{}).get('agreement_iou',.35)),prior)
    try:scheduler.run()
    finally:progress.publish(scheduler.state)
    return json.loads((out/'observations.json').read_text())
