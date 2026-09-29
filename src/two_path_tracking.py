"""Independent raw and rotation-only optical branches with bounded Qwen recovery."""
import json
import math
from pathlib import Path
import cv2
import numpy as np
from tracking_search import TrackingSearch
from visual_tracking import VisualTracker
from dual_tracking import observe_path,box_points,transform_points
from verification_policy import accepted_row
from tracking_selection import confidence_threshold
from box_verification import verify_box,confidence_from_verification,record_decision
from analysis_failures import output_failure
from path_candidates import PATHS,choose,combine,record
from stage_records import configure


def leveled_transform(width,height,pivot,angle):
    # Fixed diagonal canvas; scale is always 1. No rendering zoom enters analysis.
    side=int(math.ceil(2*math.hypot(width,height)))
    matrix=cv2.getRotationMatrix2D(tuple(map(float,pivot)),float(angle),1.)
    matrix[:,2]+=np.array([side/2,side/2])-pivot
    return matrix,(side,side)


def rebase_tracker(tracker,previous_image,old_matrix,new_matrix,size):
    """Move live features to the new pivot's coordinates, preserving their identity."""
    delta=np.vstack((new_matrix,[0,0,1]))@np.linalg.inv(np.vstack((old_matrix,[0,0,1])))
    tracker.gray=cv2.cvtColor(cv2.warpAffine(previous_image,new_matrix,size),cv2.COLOR_BGR2GRAY)
    tracker.corners=transform_points(tracker.corners,delta[:2])
    tracker.box=np.r_[tracker.corners.min(axis=0),tracker.corners.max(axis=0)]
    if tracker.points is not None:
        tracker.points=transform_points(tracker.points.reshape(-1,2),delta[:2]).astype(np.float32).reshape(-1,1,2)


class TwoPathSearch(TrackingSearch):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from tracking_progress import discovery_grid
        self.discovery=set(discovery_grid(0,self.meta['frames']-1,self.meta['fps'],min(2.,self.settings.get('discovery_fps',2.))))
        self.detections={}
        self.threshold=confidence_threshold(self.c)

    def branch_history(self,rows,index,direction,path):
        history=self.history(rows,index,direction)
        return [r if r.get('manual') else r['path_results'][path] for r in history if r.get('manual') or r.get('path_results',{}).get(path)]

    def detect(self,index,rows,direction,path,pivot=None):
        if index not in self.discovery:return None
        key=(index,path)
        if key in self.detections:return self.detections[key]
        history=self.branch_history(rows,index,direction,path)
        folder=self.namespace(index,'two_path_detection_'+path,history,None)
        # Recovery is at most one independent localization per grid point/path.
        # Structured-output transport retries are still allowed.
        c=dict(self.c,box_verification_retries=0)
        if path=='leveled':
            w,h=self.meta['width'],self.meta['height']
            matrix,size=leveled_transform(w,h,np.asarray(pivot if pivot is not None else [w/2,h/2]),self.gyro['frames'][index]['roll'])
            c['_analysis_view']=dict(matrix=matrix.tolist(),size=list(size))
        result=observe_path(c,dict(self.meta,cache=str(folder)),self.gyro,index,self.model,history,path,direction,self.helpers,
            verification_callback=(lambda result:self.progress.verification(index,result,path)) if self.progress else None,
            activity_callback=self.progress.activity if self.progress else None)
        result.update(candidate_id=path+'_detection',path=path,analysis_source='full_frame_detection',localized=bool(result.get('bbox')),
                      confidence_measurement='measured',confidence_frame=index)
        self.detections[key]=result
        return result

    def finish(self,index,records,previous=None):
        failures=[]
        for key,value in records.items():
            evidence=value.get('box_verification',value)
            if evidence.get('error'):
                if not output_failure(evidence):raise RuntimeError(evidence['error'])
                failures.append(dict(path=key,error=evidence['error'],model_error=evidence.get('model_error',{})))
        record(self.c['output_dir'],index,records)
        return combine(previous,dict(frame=index,time=index/self.meta['fps'],bbox=None,confidence=0,visibility='uncertain',
                       four_candidates=records,analysis_failures=failures),self.threshold)

    def localize(self,index,rows,direction='forward',region=None):
        old=rows.get(str(index),{});records=dict(old.get('four_candidates',{}))
        for path in PATHS:
            existing=choose([r for r in records.values() if r.get('path')==path],self.threshold)
            if existing and accepted_row(existing,self.threshold):continue
            result=self.detect(index,rows,direction,path)
            if result:records[result['candidate_id']]=result
        return self.finish(index,records,old)

    def propagate(self,source,index,step,rows):
        direction='forward' if step>0 else 'backward'
        branch_outputs={};all_records={};w,h=self.meta['width'],self.meta['height']
        for path in PATHS:
            seed=source if source.get('manual') else source.get('path_results',{}).get(path)
            if not seed or not seed.get('bbox'):continue
            previous_image=self.frame(source['frame'])
            raw_box=np.asarray(seed['bbox'])*[w,h,w,h]/1000
            pivot=(raw_box[:2]+raw_box[2:])/2
            matrix,size=(leveled_transform(w,h,pivot,self.gyro['frames'][source['frame']]['roll']) if path=='leveled' else (np.array([[1.,0,0],[0,1.,0]]),(w,h)))
            polygon=transform_points(seed.get('source_polygon_px') or box_points(raw_box),matrix)
            view=cv2.warpAffine(previous_image,matrix,size)
            tracker=VisualTracker(configure(self.c)).initialize(view,np.r_[polygon.min(axis=0),polygon.max(axis=0)],polygon.tolist())
            last=seed
            for i in range(source['frame']+step,index+step,step):
                image=self.frame(i);old_matrix=matrix
                if path=='leveled':
                    box=np.asarray(last['bbox'])*[w,h,w,h]/1000;pivot=(box[:2]+box[2:])/2
                    previous_matrix,size=leveled_transform(w,h,pivot,self.gyro['frames'][i-step]['roll'])
                    rebase_tracker(tracker,previous_image,old_matrix,previous_matrix,size)
                    matrix,size=leveled_transform(w,h,pivot,self.gyro['frames'][i]['roll'])
                view=cv2.warpAffine(image,matrix,size)
                if self.progress:self.progress.activity("optical")
                motion=tracker.update(view)
                if self.progress:self.progress.record('optical',i,'accepted' if motion['reliable'] else 'rejected')
                from optical_diagnostics import record as optical_record
                polygon=transform_points(tracker.corners,cv2.invertAffineTransform(matrix)) if motion['reliable'] else None
                box=np.r_[np.maximum(0,polygon.min(axis=0)),np.minimum([w,h],polygon.max(axis=0))] if polygon is not None else None
                reliable=bool(motion['reliable'] and np.all(box[2:]>box[:2]))
                candidate=dict(frame=i,time=i/self.meta['fps'],path=path,candidate_id=path+'_optical',
                    bbox=(box/[w,h,w,h]*1000).tolist() if reliable else None,source_polygon_px=polygon.tolist() if reliable else None,
                    confidence=last.get('confidence',0),confidence_measurement='inherited',confidence_frame=last.get('confidence_frame',source['frame']),
                    visibility='visible' if reliable else 'uncertain',analysis_source='optical_unverified',identity_verified=False,
                    motion_reliable=reliable,motion_quality=motion['motion_quality'],feature_count=motion.get('feature_count'),
                    localized=False,direction=direction,source_frame=source['frame'],source_to_view=matrix.tolist(),view_size=list(size),
                    rotation_pivot=pivot.tolist(),rotation_applied=self.gyro['frames'][i]['roll'] if path=='leveled' else 0,
                    motion_reason=motion.get('reason'),selection_flags=['optical_identity_unverified'])
                optical_record(self.c['output_dir'],dict(frame=i,path=path,source_frame=source['frame'],direction=direction,
                    bbox_px=box.tolist() if reliable else None,reliable=reliable,motion_quality=motion['motion_quality'],
                    feature_count=motion.get('feature_count'),uncertainty_px=motion['uncertainty_px'],reason=motion.get('reason')))
                if reliable and i==index:
                    history=self.branch_history(rows,i,direction,path);folder=self.namespace(i,'two_path_verify_'+path,history,None)
                    cropbox=(np.asarray(motion['box'])/np.tile(size,2)*1000).tolist()
                    if self.progress:self.progress.activity("verification")
                    verification=verify_box(self.c,view,cropbox,None,self.model,folder/'reference.jpg',folder/path,self.api)
                    verification.update(verification_context='optical_motion',motion_reliable=True)
                    if not verification.get('error'):record_decision(self.c,verification,folder/path/'acceptance.json')
                    candidate.update(box_verification=verification,confidence_measurement='measured',confidence_frame=i,
                        confidence=0 if verification.get('error') else confidence_from_verification(None,verification.get('description'),verification['comparison']))
                    if accepted_row(dict(candidate,identity_verified=True,analysis_source='flow_crop_validation'),self.threshold):
                        candidate.update(identity_verified=True,analysis_source='flow_crop_validation',selection_flags=[])
                    if self.progress:self.progress.verification(i,verification,path,localized=False)
                records=all_records.setdefault(i,{})
                records[candidate['candidate_id']]=candidate
                # Recovery only on the <=2 FPS grid. Both hypotheses remain recorded.
                if not reliable or (i==index and not candidate.get('identity_verified')):
                    detection=self.detect(i,rows,direction,path,pivot if reliable else None)
                    if detection:records[detection['candidate_id']]=detection
                winner=choose([v for v in records.values() if v.get('path')==path],self.threshold,last.get('candidate_id'))
                if not winner:break
                if winner['candidate_id'].endswith('_detection'):
                    raw_box=np.asarray(winner['bbox'])*[w,h,w,h]/1000
                    poly=transform_points(winner.get('source_polygon_px') or box_points(raw_box),matrix)
                    tracker.initialize(view,np.r_[poly.min(axis=0),poly.max(axis=0)],poly.tolist())
                last=winner;previous_image=image
                if i==index:branch_outputs[path]=winner
        # A lost branch can recover at a discovery checkpoint even if the other survives.
        records=all_records.setdefault(index,{})
        for path in PATHS:
            if path not in branch_outputs:
                detection=self.detect(index,rows,direction,path)
                if detection:records[detection['candidate_id']]=detection
        result=None
        for i,records in sorted(all_records.items()):
            selected=self.finish(i,records,rows.get(str(i)))
            if i==index:result=selected
        return result
