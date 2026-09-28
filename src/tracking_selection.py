"""Stateful, conservative selection between independent tracking hypotheses."""
import math
import numpy as np
from backward_tracking import confident

DEFAULTS = {'confidence_threshold': .5, 'agreement_iou': .35,
            'switch_advantage': .15, 'switch_samples': 3,
            'max_center_speed': 1000., 'motion_slack': 50.,
            'continuity_window_seconds': 2.}


def set_confidence_threshold(config, value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('Confidence threshold must be a finite number from 0 to 1')
    config.setdefault('tracking_selection',{})['confidence_threshold']=float(value)
    return float(value)


def confidence_threshold(config):
    return config.get('tracking_selection',{}).get('confidence_threshold',.5)


def overlap(a, b):
    if a is None or b is None:return None
    a,b=np.asarray(a),np.asarray(b)
    area=np.prod(np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])))
    union=np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-area
    return float(area/union) if union>0 else None


class TrackSelector:
    def __init__(self, settings=None):
        self.settings=dict(DEFAULTS,**(settings or {}))
        s=self.settings
        if (any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in s.values()) or
            not 0<=s['confidence_threshold']<=1 or not 0<=s['agreement_iou']<=1 or
            not 0<=s['switch_advantage']<=1 or int(s['switch_samples'])!=s['switch_samples'] or
            s['switch_samples']<1 or min(s['max_center_speed'],s['motion_slack'],s['continuity_window_seconds'])<0):
            raise ValueError('Invalid tracking selection settings')
        self.active=None;self.last=None;self.challenger=None;self.streak=0

    def consistent(self,row):
        if self.last is None:return True
        dt=abs(row['time']-self.last['time'])
        if dt>self.settings['continuity_window_seconds']:return True
        a=np.array(row['bbox']);b=np.array(self.last['bbox'])
        distance=np.linalg.norm((a[:2]+a[2:]-b[:2]-b[2:])/2)
        return distance<=self.settings['motion_slack']+self.settings['max_center_speed']*dt

    def choose(self,a,b,adjudicate):
        manual=next((r for r in (a,b) if r.get('manual')),None)
        if manual is not None:
            result=dict(manual,selected_path='manual',selection_reason='Human-confirmed label; no model adjudication',
                        selection_flags=[],path_switched=False,box_iou=overlap(a.get('bbox'),b.get('bbox')),
                        adjudication=None,pending_challenger=None,pending_switch_samples=0)
            self.last=result if result.get('bbox') is not None else None
            self.active=None;self.challenger=None;self.streak=0
            return result
        candidates={'raw_angle':a,'leveled':b};s=self.settings
        valid={k:r for k,r in candidates.items() if confident(r,s['confidence_threshold'])
               and not r.get('error') and not r.get('scene_cut')}
        continuity={k:self.consistent(r) for k,r in valid.items()}
        iou=overlap(a.get('bbox'),b.get('bbox'))
        disagreement=len(valid)==2 and iou<s['agreement_iou']
        flags=[];judgment=None;choice=None;reason='Neither path provides reliable tracking'
        flags.extend(sorted({flag for r in candidates.values() for flag in r.get('direction_flags',[])}))
        if any(r.get('error') for r in candidates.values()):flags.append('tracking_candidate_error')
        if any(r.get('box_verification',{}).get('error') for r in candidates.values()):flags.append('tracking_crop_verification_error')
        if any(r.get('confidence_source') in ('crop_verified_heuristic','blind_crop_text_match') and r['confidence']<s['confidence_threshold'] and r.get('bbox') is not None for r in candidates.values()):flags.append('tracking_crop_verification_uncertain')
        if any(r.get('box_verification',{}).get('version',0)>=2 and r.get('box_verification',{}).get('comparison',{}).get('target_complete') is False for r in candidates.values()):flags.append('tracking_box_incomplete')
        if disagreement:flags.append('tracking_path_disagreement')
        if valid and (disagreement or not all(continuity.values())):
            if not all(continuity.values()):flags.append('tracking_motion_discontinuity')
            try:judgment=adjudicate(candidates)
            except Exception as error:judgment={'choice':'neither','confidence':0,'error':str(error)}
            score=judgment.get('confidence',0)
            accepted=(judgment.get('choice') in valid and isinstance(score,(int,float)) and
                      math.isfinite(score) and score>=s['confidence_threshold'] and score<=1 and not judgment.get('error'))
            if accepted:
                choice=judgment['choice'];reason='Qwen adjudication: '+str(judgment.get('reason','candidate verified'))
            else:
                reason='Disagreement or motion jump unresolved; hold then widen'
                flags.append('tracking_selection_uncertain')
            self.challenger=None;self.streak=0
        elif len(valid)==1:
            choice=next(iter(valid));reason='Only this path is confident and motion-consistent'
            self.challenger=None;self.streak=0
        elif len(valid)==2:
            best=max(valid,key=lambda k:valid[k]['confidence'])
            choice=self.active if self.active in valid else best
            reason='Candidates agree; preserve current path'
            challenger=next(k for k in valid if k!=choice)
            if valid[challenger]['confidence']-valid[choice]['confidence']>=s['switch_advantage']:
                self.streak=self.streak+1 if self.challenger==challenger else 1
                self.challenger=challenger
                if self.streak>=s['switch_samples']:
                    choice=challenger;reason='Sustained confidence advantage; switch path'
                    self.challenger=None;self.streak=0
            else:self.challenger=None;self.streak=0
        else:
            self.challenger=None;self.streak=0;flags.append('tracking_selection_uncertain')
        switched=choice is not None and self.active is not None and choice!=self.active
        result=dict(candidates[choice]) if choice else {
            'frame':a['frame'],'time':a['time'],'bbox':None,'confidence':0,'visibility':'uncertain',
            'shoreline':None,'level_confidence':0}
        if choice:
            if judgment:result['confidence']=min(result['confidence'],judgment['confidence'])
            self.active=choice;self.last=result
        result.update(selected_path=choice or 'neither',selection_reason=reason,
                      selection_flags=flags,path_switched=switched,box_iou=iou,
                      adjudication=judgment,pending_challenger=self.challenger,pending_switch_samples=self.streak)
        return result


def frame_provenance(observations, count, supported, threshold=.5):
    """Label interpolated playback frames without claiming a new model decision."""
    rows=sorted(observations,key=lambda r:r['frame'])
    from motion_render import motion_usable
    valid=[r for r in rows if motion_usable(r) or (confident(r,threshold) and not r.get('error'))]
    indices=np.array([r['frame'] for r in rows]);vi=np.array([r['frame'] for r in valid])
    result=[]
    for index in range(count):
        nearest=rows[int(np.abs(indices-index).argmin())]
        source=[]
        if supported[index] and valid:
            position=int(np.searchsorted(vi,index))
            if position<len(valid) and vi[position]==index:source=[valid[position]]
            else:source=[valid[max(0,position-1)],valid[min(len(valid)-1,position)]]
        paths=list(dict.fromkeys(r.get('selected_path','manual' if r.get('manual') else 'unknown') for r in source))
        result.append({'selected_path':paths[0] if len(paths)==1 else 'interpolated' if paths else 'neither',
                       'selection_source_samples':list(dict.fromkeys(r['frame'] for r in source)),
                       'selection_source_paths':paths,'selection_sample_frame':nearest['frame'],
                       'selection_source_directions':list(dict.fromkeys(r.get('direction_choice',r.get('direction','forward')) for r in source)),
                       'selection_reason':nearest.get('selection_reason'),
                       'selection_flags':nearest.get('selection_flags',[]),
                       'selection_is_direct':index==nearest['frame']})
    return result
