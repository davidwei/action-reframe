"""Per-branch verification scheduling. Decisions never manufacture identity evidence."""
import copy
import math

VERSION=1
DEFAULTS=dict(mode='adaptive',tiny_box_ratio=.5,stable_seconds=.5,intermediate_seconds=.25)


def settings(config):
    s=dict(DEFAULTS,**config.get('adaptive_verification',{}))
    if s['mode'] not in ('off','evaluation','adaptive'):raise ValueError('Invalid adaptive verification mode')
    for key in ('tiny_box_ratio','stable_seconds','intermediate_seconds'):
        if isinstance(s[key],bool) or not isinstance(s[key],(int,float)) or not math.isfinite(s[key]) or s[key]<=0:
            raise ValueError('Invalid adaptive setting: '+key)
    if s['tiny_box_ratio']>1:raise ValueError('Tiny-box ratio must be <= 1')
    from zoom_path import minimum_crop_size
    minimum_crop_size(1,config.get('minimum_crop_short_side',180))
    return s


class Schedule:
    def __init__(self,config,seed,direction,fps):
        self.options=settings(config);self.mode=self.options['mode'];self.fps=fps
        self.threshold=config.get('minimum_crop_short_side',180)*self.options['tiny_box_ratio']
        self.spacing=1/config.get('analysis_fps',10)
        saved=seed.get('verification_schedule_state',{})
        self.state=copy.deepcopy(saved) if saved.get('direction')==direction else dict(direction=direction,last_pass=None,last_attempt=None,isolated=False,retention=1.,history=[],urgent=False)
        if seed.get('manual') or not saved and seed.get('identity_verified'):
            self.passed(seed['frame'],seed.get('box_verification'),manual=bool(seed.get('manual')))

    def passed(self,frame,verification=None,manual=False):
        v=verification or {}
        self.state.update(last_pass=frame,last_attempt=frame,retention=1.,urgent=False,
            isolated=manual or (v.get('description',{}).get('composition')=='isolated_subject' and
                               v.get('comparison',{}).get('localization_support')=='supported'))

    def decide(self,frame,motion,box,center):
        s=self.state;w,h=box[2]-box[0],box[3]-box[1];tiny=min(w,h)<self.threshold
        q=motion.get('motion_quality',0);n=motion.get('feature_count',0);e=motion.get('flow_error_px')
        s['retention']*=q
        hist=s['history'];window=max(1,round(self.fps*.1));old=next((x for x in reversed(hist) if abs(frame-x['frame'])>=window),None)
        scale=motion.get('scale',1)
        scale100=scale*math.prod(x['scale'] for x in hist if old and abs(frame-x['frame'])<abs(frame-old['frame']))
        jump=math.dist(center,old['center'])/max(1,old['diagonal']) if old else 0
        abrupt=bool(old and (not .9<=scale100<=1.1 or jump>.25))
        weak=q<.5 or n<8 or s['retention']<.3 or e is not None and e>1
        strong=q>=.7 and n>=12 and s['retention']>=.5 and e is not None and e<=.75 and not abrupt
        s['urgent']=s['urgent'] or weak or abrupt
        age=abs(frame-s['last_pass'])/self.fps if s['last_pass'] is not None else None
        elapsed=abs(frame-s['last_attempt'])/self.fps if s['last_attempt'] is not None else None
        interval=self.options['stable_seconds'] if strong else self.options['intermediate_seconds']
        due=s['urgent'] or not s['isolated'] or age is None or age>=interval
        allowed=elapsed is None or elapsed+1e-9>=self.spacing
        verify=not tiny and due and allowed
        reason=('crop_too_small' if tiny else 'rate_limit' if due and not allowed else
                'motion_warning' if s['urgent'] else 'localization_uncertain' if not s['isolated'] else
                'periodic_check' if due else 'recent_verified_tracking')
        hist.append(dict(frame=frame,center=list(map(float,center)),diagonal=math.hypot(w,h),scale=scale))
        s['history']=[x for x in hist if abs(frame-x['frame'])<=window+1]
        return dict(mode=self.mode,proposed_verify=verify,reason=reason,tiny=tiny,box_pixels=[float(w),float(h)],
            tiny_threshold_px=self.threshold,last_pass_frame=s['last_pass'],identity_age_seconds=age,
            motion_strong=strong,feature_retention_estimate=s['retention'],flow_error_px=e,
            scale_100ms=scale100,center_jump_100ms=jump,performed=False)

    def result(self,frame,verification,accepted):
        self.state['last_attempt']=frame;self.state['urgent']=False
        if accepted:self.passed(frame,verification)
        else:self.state['isolated']=False

    def snapshot(self):return copy.deepcopy(self.state)
