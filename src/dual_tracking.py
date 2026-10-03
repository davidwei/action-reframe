"""Independent raw+angle and leveled-image tracking, stored in source coordinates."""
from verification_policy import target_description, verification_decision
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading
from tracking_response import structured_tracking, validate_detection, ABSENCE_HINT
from analysis_failures import path_failures
from concurrent.futures import ThreadPoolExecutor
from tracking_selection import TrackSelector

import cv2
import numpy as np
from backward_tracking import bidirectional_pass
from leveling_annotations import tracking_attitude
from leveling import extract_gyro

VERSION = 8
PATHS = ('raw_angle', 'leveled')


def transform_points(points, matrix):
    return np.c_[np.asarray(points, dtype=float), np.ones(len(points))] @ matrix.T


def box_points(box):
    x1, y1, x2, y2 = box
    return np.array([[x1,y1], [x2,y1], [x2,y2], [x1,y2]], dtype=float)


def expanded_rotation(width, height, angle):
    matrix = cv2.getRotationMatrix2D((width/2, height/2), angle, 1)
    corners = transform_points(box_points([0,0,width,height]), matrix)
    lower, upper = corners.min(axis=0), corners.max(axis=0)
    matrix[:,2] -= lower
    return matrix, tuple(np.ceil(upper-lower).astype(int))


def source_box(box, matrix, view_size, source_size):
    """Inverse-transform all four corners; retain polygon before clipping its AABB."""
    if box is None:
        return None, None
    points = box_points(np.asarray(box)*np.tile(view_size,2)/1000)
    polygon = transform_points(points, cv2.invertAffineTransform(matrix))
    lo = np.maximum(polygon.min(axis=0), 0)
    hi = np.minimum(polygon.max(axis=0), source_size)
    if np.any(hi <= lo):
        return None, polygon.tolist()
    return (np.r_[lo,hi]/np.tile(source_size,2)*1000).tolist(), polygon.tolist()


def box_iou(a, b):
    if a is None or b is None:return None
    a,b=np.asarray(a),np.asarray(b)
    intersection=np.prod(np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])))
    union=np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-intersection
    return float(intersection/union) if union>0 else None


def observe_path(c, meta, gyro, index, model, history, path, direction, helpers,verification_callback=None,activity_callback=None):
    frame_loader, completion, save = helpers
    history=[r for r in history if not r.get('error') and not r.get('box_verification',{}).get('error')]
    angle=gyro['frames'][index]['roll']
    cache=Path(meta['cache'])
    signature=hashlib.sha256(json.dumps([VERSION,path,direction,index,angle,model,target_description(c),
        c.get('adaptive_verification'),c.get('minimum_crop_short_side',180),c.get('temporal_context'),c.get('reference_frames',[]),c.get('verify_boxes',True),c.get('_search_region'),c.get('_analysis_view'),c.get('box_verification_retries',2),c.get('tracking_selection',{}).get('confidence_threshold',.5),history],sort_keys=True).encode()).hexdigest()[:24]
    result_path=cache/f'{signature}.json'
    if result_path.exists() and not c.get('stage_store_dir'):
        result=json.loads(result_path.read_text())
        if not result.get('error') and not result.get('box_verification',{}).get('error'):
            if verification_callback and result.get('box_verification'):verification_callback(dict(result['box_verification'],cache_hit=True))
            return result
    image=frame_loader(c,meta,index)
    h,w=image.shape[:2]
    region=c.get('_search_region',[0,0,w,h])
    x1,y1,x2,y2=region
    matrix,size=(expanded_rotation(x2-x1,y2-y1,angle) if path=='leveled' else
                 (np.array([[1.,0,0],[0,1.,0]]),(int(x2-x1),int(y2-y1))))
    matrix[:,2]-=matrix[:,:2]@np.array([x1,y1])
    if path=='leveled' and c.get('_analysis_view'):
        matrix=np.asarray(c['_analysis_view']['matrix'],float);size=tuple(c['_analysis_view']['size'])
    view=cv2.warpAffine(image,matrix,size,borderMode=cv2.BORDER_CONSTANT)
    current_path=cache/f'{index:07d}_{path}_view.jpg'
    cv2.imwrite(str(current_path),view)
    images=[cache/'reference.jpg',current_path]
    prompt=f'''Track the user-selected object in this CURRENT frame during {direction} traversal.
Image 1: original target reference crop. Image 2: current {'leveled' if path=='leveled' else 'raw'} full frame, clean.
Locate the target afresh in clean IMAGE 2. No previous box coordinates or target outline are supplied.
Additional human-labeled target crops are identity references at their labeled timestamps, not current-position hints.
Target: {target_description(c)}
The user accepts a blurry, distant or low-resolution target. Track it whenever visible evidence supports its identity; do not reject it or lower confidence solely because it is blurry.
Use coarse shape, color, equipment and motion context when fine details are unreadable. Do not invent missing details; return uncertainty only when the available evidence cannot distinguish the target.
Current source frame {index}, time {index/meta['fps']:.3f}s. Source size {w}x{h}; IMAGE 2 size {size[0]}x{size[1]}.
{'IMAGE 2 is a local SEARCH CROP, not the full source. Locate the target within this crop and return coordinates normalized to its full displayed extent; code maps them back to source coordinates.' if c.get('_search_region') else ''}
Current configured leveling correction is {angle:.6f} degrees. Positive values require counterclockwise correction.
{'IMAGE 2 has already been rotated counterclockwise by that angle, with expanded black borders to avoid cutting content. Do not rotate again. Black padding is not scene content.' if path=='leveled' else 'IMAGE 2 has NOT been rotated. Use the angle to understand camera tilt; return coordinates in the RAW image.'}
Additional HISTORY full frames use ORIGINAL RAW views, even in the leveled path. Use their visual motion context; return coordinates only in IMAGE 2.
Use visible target parts and equipment. Apply exclusions from the approved target description; do not invent project-specific exclusions. Do not switch identity. If absent or uncertain, return null and honest confidence.
Coordinates: IMAGE 2 top-left is (0,0), bottom-right is (1000,1000). X increases rightward and Y downward.
Normalize X by the FULL IMAGE 2 width and Y by its FULL height, including any black padding. Return [xmin,ymin,xmax,ymax]. Do not unrotate your answer.
After proposing the coordinates, inspect the region they enclose. Describe ACTUAL contents there, including target parts, cut-off parts and unrelated background; do not repeat the intended target description.
If that region does not contain the target, correct the box before answering or return null. box_note must describe your FINAL box.
Return ONLY JSON: {{"bbox":[left,top,right,bottom] or null,"confidence":0.0,"visibility":"visible|partial|absent|uncertain","scene_cut":false,"note":"identity and uncertainty evidence","box_note":"actual contents inside final box and any truncation; unavailable if bbox is null"}}.
Output bbox normalized 0..1000 relative to IMAGE 2, NOT source pixels or history coordinates.'''
    prompt+='\n'+ABSENCE_HINT
    retries=c.get('box_verification_retries',2)
    if type(retries) is not int or not 0<=retries<=2:raise ValueError('box_verification_retries must be 0, 1 or 2')
    detection_config=dict(c,temporal_context=dict(c.get('temporal_context',{}),omit_box_coordinates=True))
    attempts=[];feedback=''
    for attempt in range(retries+1):
        attempt_cache=cache/'detection_requests'/signature/str(attempt)
        attempt_cache.mkdir(parents=True,exist_ok=True)
        raw=None
        try:
            if activity_callback:activity_callback("discovery")
            data,audit=structured_tracking(completion,detection_config,dict(meta,cache=str(attempt_cache)),index,direction,history,model,
                images,prompt+feedback,650,validate_detection)
            raw=data['raw'];box=data['bbox'];score=data['confidence']
            original,polygon=source_box(box,matrix,size,(w,h))
            data.update(bbox=original,confidence=score if original is not None else 0,
                        qwen_view_bbox=box,source_polygon_px=polygon,raw=raw,temporal_context=audit)
            data['model_confidence']=score
            if box is not None and c.get('verify_boxes',True):
                from box_verification import verify_box, confidence_from_verification
                from reframe import api
                trusted_reference=next((Path(entry['path']) for entry in reversed(audit.get('images',[]))
                                        if entry.get('kind')=='human_target_crop'),cache/'reference.jpg')
                if activity_callback:activity_callback("verification")
                # Tiny independent proposals are verified with surrounding image context,
                # never by repeatedly asking for an unreadably small crop alone.
                from adaptive_verification import settings as adaptive_settings
                adaptive=adaptive_settings(c);verification_box=box
                pixels=np.array(box)*np.tile(size,2)/1000
                threshold=c.get('minimum_crop_short_side',180)*adaptive['tiny_box_ratio']
                if adaptive['mode']=='adaptive' and min(pixels[2:]-pixels[:2])<threshold:
                    center=(pixels[:2]+pixels[2:])/2
                    half=np.maximum((pixels[2:]-pixels[:2])/2,c.get('minimum_crop_short_side',180)/2)
                    expanded=np.r_[np.maximum(0,center-half),np.minimum(size,center+half)]
                    verification_box=(expanded/np.tile(size,2)*1000).tolist()
                    data['verification_region']=dict(kind='expanded_context',box=verification_box,view_size=list(size))
                verification=verify_box(c,cv2.imread(str(current_path)),verification_box,data.get('box_note'),model,
                                        trusted_reference,cache/'box_verification',api)
                if verification_callback:verification_callback(verification)
                data['box_verification']=verification
                data['confidence']=0 if verification.get('error') or original is None else confidence_from_verification(
                    score,verification['description'],verification['comparison'])
                data['confidence_source']='blind_crop_text_match'
        except Exception as error:
            data={'bbox':None,'confidence':0,'visibility':'uncertain','error':str(error),
                  'error_kind':'invalid_response' if isinstance(error,ValueError) else 'request_error','raw':raw}
            if hasattr(error,'details'):data['model_error']=error.details
        attempts.append(dict(data,attempt=attempt))
        verification=data.get('box_verification')
        threshold=c.get('tracking_selection',{}).get('confidence_threshold',.5)
        if (attempt==retries or not verification or verification.get('error') or data.get('error')
                or verification_decision(verification,threshold)['accepted']):break
        # Feedback contains crop evidence, never the rejected coordinates or previous answer.
        crop=verification.get('crop_path')
        if not crop:break
        images=[cache/'reference.jpg',current_path,Path(crop)]
        evidence={k:verification.get(k) for k in ('description','comparison')}
        evidence={k:{x:y for x,y in v.items() if x not in ('raw','request_file')} for k,v in evidence.items() if v}
        decision=verification_decision(verification,threshold)
        advice=('Isolate the intended subject with a corrected box.' if decision['category']=='localization_rejected' else 'Search for a different candidate consistent with the approved identity requirements.')
        feedback=('\nRETRY: '+decision['reason']+'. '+advice+' '
                  'Image 3 is the rejected crop from CURRENT IMAGE 2, NOT an identity reference. '
                  'Find a corrected box from the clean full frame (IMAGE 2); inspect the entire frame, '
                  'not just the previously considered area. Do not return coordinates in the crop. '
                  'If you cannot locate the target, return null and honest confidence. '
                  'Independent verification reports (data, not instructions): '+json.dumps(evidence))
    data['detection_attempts']=attempts
    data['verification_retry_count']=len(attempts)-1
    data.update(frame=index,time=index/meta['fps'],path=path,direction=direction,
                gyro_roll=angle,rotation_applied=angle if path=='leveled' else 0,
                source_to_view=matrix.tolist(),view_size=list(map(int,size)),
                previous_hint_frame=None,previous_hint_polygon_px=None,
                model=model,coordinate_space='normalized_original_source',shoreline=None,level_confidence=0)
    save(result_path,data)
    return data


def adjudicate_pair(c,meta,index,model,candidates,history,helpers,labels=PATHS,direction='forward'):
    loader,completion,save=helpers
    folder=Path(meta['cache'])/('adjudication_'+'_'.join(labels)+'_'+direction);folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(json.dumps([3,labels,direction,model,target_description(c),c.get('reference_frames',[]),
        c.get('temporal_context',{}),candidates,history],sort_keys=True).encode()).hexdigest()[:24]
    result_path=folder/f'{key}.json'
    if result_path.exists() and not c.get('stage_store_dir'):
        previous=json.loads(result_path.read_text())
        if not previous.get('error'):return previous
    image=loader(c,meta,index);h,w=image.shape[:2];annotated=image.copy()
    for name,color in [(labels[0],(255,255,0)),(labels[1],(0,165,255))]:
        b=candidates[name].get('bbox')
        if b is None:continue
        x1,y1,x2,y2=np.round(np.array(b)*[w,h,w,h]/1000).astype(int)
        cv2.rectangle(annotated,(x1,y1),(x2,y2),color,2)
        cv2.putText(annotated,name,(x1,max(20,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.6,color,2)
    clean=folder/f'{index:07d}_raw.jpg';marked=folder/f'{key}_candidates.jpg'
    cv2.imwrite(str(clean),image);cv2.imwrite(str(marked),annotated)
    prompt=f'''Adjudicate two independent tracking candidates for the SAME user-selected target.
Image 1 is the target reference. Image 2 is the CURRENT RAW frame. Image 3 marks candidates:
{labels[0]} = cyan, {labels[1]} = orange. All candidate boxes use normalized ORIGINAL RAW coordinates.
Target: {target_description(c)}. Current frame: {index}.
Candidates: {json.dumps({k:{'bbox':r.get('bbox'),'note':r.get('note')} for k,r in candidates.items()})}
The user accepts blurry or low-resolution targets. Blur alone is not a reason to choose neither or lower confidence; use the available shape, color and motion evidence. Unreadable fine details are not identity contradictions. Remain uncertain if the visible evidence cannot distinguish the target.
Use visible identity evidence and supplied selected-track motion history. Do not choose merely because a candidate has a box.
If neither can be verified, choose neither. A camera movement can explain a jump, but confirm it from image evidence.
Return ONLY JSON: {{"choice":"{labels[0]}|{labels[1]}|neither","confidence":0.0,"reason":"identity and motion evidence"}}.'''
    try:
        def validate(result):
            score=result.get('confidence')
            if result.get('choice') not in (*labels,'neither') or isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:
                raise ValueError('Invalid adjudication response')
        result,audit=structured_tracking(completion,c,dict(meta,cache=str(folder/key)),index,direction,
            [r for r in history if not r.get('error') and not r.get('box_verification',{}).get('error')],model,
            [Path(meta['cache'])/'reference.jpg',clean,marked],prompt,350,validate,'tracking adjudication')
        result['temporal_context']=audit
    except Exception as error:
        result={'choice':'neither','confidence':0,'error':str(error),'reason':'Adjudication failed'}
        if hasattr(error,'details'):result['model_error']=error.details
    save(result_path,result);return result


def run_dual(c, meta, model, api_helpers, single=None):
    """Pair requests concurrently, preserve branch histories, select a third track."""
    out=Path(c['output_dir']);save=api_helpers[2]
    render_path=c.get('tracking_render_path','selected')
    if render_path not in (*PATHS,'selected'):raise ValueError('Invalid tracking_render_path')
    gyro=extract_gyro(c['video'],meta) if c.get('leveling_source','gyro')=='gyro' else tracking_attitude(c,meta)
    save(out/'gyro.json',gyro)
    from manual_tracking import manual_observations
    manual=manual_observations(c,meta)
    indices=sorted(set(meta['samples']) | set(manual))
    if single is not None:
        last=min(indices,key=lambda i:abs(i/meta['fps']-single));indices=[i for i in indices if i<=last]
    metas={};results={path:[] for path in PATHS};selected=[];comparison=[]
    selector=TrackSelector(c.get('tracking_selection'))
    for path in PATHS:
        namespace=Path(meta['cache'])/f'dual_v{VERSION}_{path}'
        namespace.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(meta['cache'])/'reference.jpg',namespace/'reference.jpg')
        metas[path]=dict(meta,cache=str(namespace))
    failure_file=out/'analysis_failures.json'
    failures_by_frame={entry['frame']:entry for entry in json.loads(failure_file.read_text())} if failure_file.exists() else {}
    failure_lock=threading.Lock()
    def record_failures(index,candidates,direction):
        failures=path_failures(candidates)
        if failures:
            with failure_lock:
                entry=failures_by_frame.setdefault(index,dict(frame=index,time=index/meta['fps'],failures=[]))
                for failure in failures:
                    failure=dict(failure,direction=direction)
                    if failure not in entry['failures']:entry['failures'].append(failure)
                save(failure_file,[failures_by_frame[i] for i in sorted(failures_by_frame)])
        return failures
    def select_pair(a,b,selector,history):
        row=selector.choose(a,b,lambda candidates:adjudicate_pair(c,meta,a['frame'],model,candidates,history,api_helpers))
        if row.get('adjudication',{}):record_failures(a['frame'],{'adjudication':row['adjudication']},'selection')
        paired={'frame':a['frame'],'time':a['time'],'raw_angle':a,'leveled':b,
                'box_iou':row['box_iou'],'selected':row}
        return row,paired
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index in indices:
            pending={} if index in manual else {path:pool.submit(observe_path,c,metas[path],gyro,index,model,
                                      list(results[path]),path,'forward',api_helpers) for path in PATHS}
            pair={path:dict(manual[index],path=path,gyro_roll=gyro['frames'][index]['roll']) if index in manual else pending[path].result() for path in PATHS}
            frame_failures=record_failures(index,pair,'forward')
            for path in PATHS:
                results[path].append(pair[path]);save(out/f'tracking_{path}_forward.json',results[path])
            row,paired=select_pair(pair['raw_angle'],pair['leveled'],selector,selected)
            row['analysis_failures']=frame_failures
            selected.append(row);comparison.append(paired)
            save(out/'tracking_selected_forward.json',selected)
            save(out/'tracking_comparison.json',comparison)
            save(out/'analysis_progress.json',{'stage':'paired_forward','completed':len(selected),'total':len(indices),
                'frame':index,'time':index/meta['fps'],'analysis_fps':c['analysis_fps'],
                'selected_path':row['selected_path'],'candidate_errors':{p:r['error'] for p,r in pair.items() if r.get('error')}})
            print(f"Dual paired {len(selected)}/{len(indices)} t={row['time']:.2f} selected={row['selected_path']} reason={row['selection_reason']}",flush=True)
            # Frame-local output failures are reviewable gaps; service/system failures raise in record_failures.
        save(out/'observations_first_pass.json',selected if render_path=='selected' else results[render_path])
        if c.get('backward_recovery',True) and single is None:
            def recover(path):
                def attempt(current,seed,history):
                    row=observe_path(c,metas[path],gyro,current['frame'],model,history,path,'backward',api_helpers)
                    row['analysis_failures']=record_failures(current['frame'],{path:row},'backward')
                    return row
                def resolve(forward,backward,history):
                    result=adjudicate_pair(c,metas[path],forward['frame'],model,
                        {'forward':forward,'backward':backward},history,api_helpers,
                        labels=('forward','backward'),direction='backward')
                    record_failures(forward['frame'],{'adjudication_'+path:result},'backward')
                    return result
                def progress(report,row):
                    judgment=row.get('direction_comparison',{}).get('adjudication')
                    if judgment:record_failures(row['frame'],{'adjudication_'+path:judgment},'backward')
                    save(out/f'tracking_{path}_backward_progress.json',
                         {'frame':row['frame'],'time':row['time'],'attempted_samples':report['attempted_samples'],
                          'direction_choice':row['direction_choice'],'reason':row['direction_reason']})
                    print(f"Backward {path} t={row['time']:.2f} choice={row['direction_choice']} {row['direction_reason']}",flush=True)
                settings=c.get('tracking_selection',{})
                rows,report=bidirectional_pass(results[path],attempt,resolve,
                    threshold=settings.get('confidence_threshold',.5),agreement_iou=settings.get('agreement_iou',.35),progress=progress)
                save(out/f'tracking_{path}_directions.json',[
                    {'frame':r['frame'],'time':r['time'],'chosen_direction':r.get('direction_choice'),
                     'reason':r.get('direction_reason'),'comparison':r.get('direction_comparison')} for r in rows])
                save(out/f'tracking_{path}_backward_report.json',report)
                return rows
            save(out/'analysis_progress.json',{'stage':'backward_recovery','completed':len(indices),'total':len(indices)})
            pending={path:pool.submit(recover,path) for path in PATHS}
            results={path:future.result() for path,future in pending.items()}
    for path in PATHS:save(out/f'tracking_{path}.json',results[path])
    # Recoveries may change availability; recompute selection chronologically.
    selector=TrackSelector(c.get('tracking_selection'));final=[];comparison=[]
    save(out/'analysis_progress.json',{'stage':'final_selection','completed':0,'total':len(indices)})
    for a,b in zip(results['raw_angle'],results['leveled']):
        row,paired=select_pair(a,b,selector,final);final.append(row);comparison.append(paired)
        save(out/'analysis_progress.json',{'stage':'final_selection','completed':len(final),'total':len(indices)})
    save(out/'tracking_selected.json',final);save(out/'tracking_comparison.json',comparison)
    output=final if render_path=='selected' else results[render_path]
    save(out/'observations.json',output)
    save(out/'analysis_progress.json',{'stage':'complete','completed':len(indices),'total':len(indices)})
    return output
