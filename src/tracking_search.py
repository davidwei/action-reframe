"""Qwen identity checks and local/full-frame dual-path localization for anchors."""
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np
from dual_tracking import VERSION as DETECTION_VERSION
from box_verification import VERSION as VERIFICATION_VERSION
from dual_tracking import observe_path,adjudicate_pair,box_points,expanded_rotation,transform_points
from tracking_selection import TrackSelector,confidence_threshold
from box_verification import verify_box,confidence_from_verification
from lookout.events import timed as lookout_timed,count as lookout_count
from analysis_failures import path_failures,output_failure
from visual_tracking import VisualTracker,relaxed_box,too_large

VERSION=2

class TrackingSearch:
    def __init__(self,config,meta,gyro,model,helpers,api):
        self.c=config;self.meta=meta;self.gyro=gyro;self.model=model
        self.loader,self.completion,self.save=helpers;self.helpers=helpers;self.api=api
        self.progress=None
        self.settings=config.get('anchor_tracking',{})
        self.folder=Path(meta['cache'])/'anchor_search';self.folder.mkdir(exist_ok=True)

    def frame(self,index):return self.loader(self.c,self.meta,index)

    def history(self,rows,index,direction):
        return sorted([r for r in rows.values() if not r.get('error') and (not r.get('analysis_failures') or (r.get('bbox') is not None and r.get('confidence',0)>=confidence_threshold(self.c))) and (r['frame']<index if direction=='forward' else r['frame']>index)],key=lambda r:r['frame'],reverse=direction=='backward')

    def namespace(self,index,kind,history,region):
        key=hashlib.sha256(json.dumps([VERSION,DETECTION_VERSION,VERIFICATION_VERSION,self.model,index,kind,history,region,self.c],sort_keys=True).encode()).hexdigest()[:24]
        folder=self.folder/key;folder.mkdir(exist_ok=True)
        reference=Path(self.meta['cache'])/'reference.jpg'
        manual=next((r for r in reversed(history) if r.get('manual') and r.get('bbox')),None)
        if manual:
            image=self.frame(manual['frame'])
            from label_geometry import human_crop
            cv2.imwrite(str(folder/'reference.jpg'),human_crop(image,manual))
        else:(folder/'reference.jpg').write_bytes(reference.read_bytes())
        return folder

    @lookout_timed("detection")
    def localize(self,index,rows,direction='forward',region=None):
        history=self.history(rows,index,direction);folder=self.namespace(index,'detect',history,region)
        result_file=folder/'selected.json'
        if result_file.exists():
            cached=json.loads(result_file.read_text())
            if not cached.get('error'):
                if not cached.get('analysis_failures'):
                    cached['analysis_failures']=path_failures(cached.get('candidates',{}))
                if self.progress:
                    for path,candidate in cached.get('candidates',{}).items():
                        if candidate.get('box_verification'):self.progress.verification(index,candidate['box_verification'],path,cached=True)
                return cached
        candidates={}
        def detect(path):
            sub=folder/path;sub.mkdir(exist_ok=True);(sub/'reference.jpg').write_bytes((folder/'reference.jpg').read_bytes())
            c=dict(self.c)
            if region is not None:c['_search_region']=region
            return observe_path(c,dict(self.meta,cache=str(sub)),self.gyro,index,self.model,history,path,direction,self.helpers,
                                verification_callback=(lambda result:self.progress.verification(index,result,path)) if self.progress else None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending={p:pool.submit(detect,p) for p in ('raw_angle','leveled')}
            candidates={p:f.result() for p,f in pending.items()}
        for candidate in candidates.values():
            candidate.update(analysis_source='local_detection' if region is not None else 'full_frame_detection',localized=bool(candidate.get('bbox')),search_region_px=region)
        failures=path_failures(candidates)
        selected=TrackSelector(self.c.get('tracking_selection')).choose(candidates['raw_angle'],candidates['leveled'],
            lambda pair:adjudicate_pair(self.c,dict(self.meta,cache=str(folder)),index,self.model,pair,history,self.helpers,direction=direction))
        selected.update(localized=bool(selected.get('bbox')),analysis_source='local_detection' if region is not None else 'full_frame_detection',
                        search_region_px=region,candidates=candidates,last_localized_frame=index,
                        last_localized_box=selected.get('bbox'),motion_uncertainty_px=0.)
        selected['analysis_failures']=failures
        if selected.get('adjudication',{}):
            judgment=selected['adjudication']
            if judgment.get('error'):
                if not output_failure(judgment):raise RuntimeError(judgment['error'])
                selected['analysis_failures'].append(dict(path='adjudication',error=judgment['error']))
        self.save(result_file,selected);return selected

    @lookout_timed("propagation")
    def propagate(self,source,index,step,rows):
        direction='forward' if step>0 else 'backward';history=self.history(rows,index,direction)
        frame=self.frame(source['frame']);h,w=frame.shape[:2]
        box=np.asarray(source['bbox'])*[w,h,w,h]/1000
        tracker=VisualTracker().initialize(frame,box,source.get('source_polygon_px'));motion=None
        for i in range(source['frame']+step,index+step,step):
            frame=self.frame(i)
            try:motion=tracker.update(frame)
            except Exception:
                if self.progress:self.progress.record('optical',i,'errored')
                raise
            if self.progress:self.progress.record('optical',i,'accepted' if motion['reliable'] else 'rejected')
            lookout_count('optical.update',outcome='success' if motion['reliable'] else 'lost')
            if not motion['reliable']:break
        image=self.frame(index)
        if motion is None:raise ValueError('Propagation needs a different frame')
        uncertainty=source.get('motion_uncertainty_px',0)+motion['uncertainty_px']
        region=relaxed_box(motion['box'],image.shape,uncertainty,motion['reliable'],
                           self.settings.get('padding_fraction',.15),self.settings.get('min_padding_px',8))
        region=[int(np.floor(v)) if j<2 else int(np.ceil(v)) for j,v in enumerate(region)]
        localized=np.asarray(source.get('last_localized_box') or source['bbox'])*[w,h,w,h]/1000
        localize=not motion['reliable'] or too_large(region,localized,self.settings.get('max_dimension_ratio',1.5),self.settings.get('max_area_ratio',2.))
        candidates={};failures=[]
        if not localize:
            folder=self.namespace(index,'validate',history,region)
            for path in ('raw_angle','leveled'):
                angle=self.gyro['frames'][index]['roll'] if path=='leveled' else 0
                matrix,size=expanded_rotation(w,h,angle)
                view=cv2.warpAffine(image,matrix,size)
                polygon=transform_points(box_points(region),matrix)
                cropbox=(np.r_[polygon.min(axis=0),polygon.max(axis=0)]/np.tile(size,2)*1000).tolist()
                verification=verify_box(self.c,view,cropbox,None,self.model,folder/'reference.jpg',folder/path,self.api)
                if self.progress:self.progress.verification(index,verification,path,localized=False)
                if verification.get('error'):
                    if not output_failure(verification):raise RuntimeError(verification['error'])
                    failures.append(dict(path=path,error=verification['error'],model_error=verification.get('model_error',{})))
                    candidates[path]=dict(frame=index,time=index/self.meta['fps'],bbox=None,confidence=0,visibility='uncertain',box_verification=verification)
                    continue
                score=confidence_from_verification(None,verification['description'],verification['comparison'])
                predicted=(np.asarray(motion['box'])/[w,h,w,h]*1000).tolist()
                candidates[path]=dict(frame=index,time=index/self.meta['fps'],bbox=predicted,confidence=score,visibility='visible',
                    confidence_source='blind_crop_text_match',box_verification=verification,path=path,direction=direction,
                    source_polygon_px=box_points(motion['box']).tolist(),analysis_source='flow_crop_validation',localized=False,
                    search_region_px=region,motion_quality=motion['motion_quality'],motion_uncertainty_px=uncertainty,
                    last_localized_box=source.get('last_localized_box') or source['bbox'],last_localized_frame=source.get('last_localized_frame',source['frame']))
            from verification_policy import accepted_row
            valid=[r for r in candidates.values() if accepted_row(r,confidence_threshold(self.c))]
            if valid:
                chosen=max(valid,key=lambda r:r['confidence'])
                if self.progress:self.progress.detection('optical',index,chosen)
                return dict(chosen,selected_path=chosen['path'],selection_reason='Optical-flow prediction with verified relaxed crop; box not independently localized',
                            selection_flags=['tracking_propagated_box'],candidates=candidates,analysis_failures=failures)
        if self.progress and motion['reliable']:
            self.progress.detection('optical',index,max(candidates.values(),key=lambda r:r['confidence']) if candidates else {})
        result=self.localize(index,rows,direction,region)
        result['analysis_failures']=failures+result.get('analysis_failures',[])
        result.update(motion_quality=motion['motion_quality'],motion_reason=motion.get('reason'),propagation_validation=candidates)
        return result
