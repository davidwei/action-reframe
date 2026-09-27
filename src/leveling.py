"""Independent visual leveling and DJI attitude comparison.

Telemetry mapping is explicit and provisional until camera calibration is available.
Raw Qwen observations never receive telemetry or previous leveling estimates.
"""
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import struct

import av
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

VISUAL_VERSION = 3


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False)); temp.replace(path)


def _varint(b, i):
    value = 0
    for shift in range(0, 70, 7):
        byte = b[i]; i += 1; value |= (byte & 127) << shift
        if not byte & 128: return value, i
    raise ValueError('Invalid protobuf integer')


def fields(b):
    result = []; i = 0
    while i < len(b):
        tag, i = _varint(b, i); number, wire = tag >> 3, tag & 7
        if not number: raise ValueError('Invalid field')
        if wire == 0: value, i = _varint(b, i)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4; value = b[i:i+size]; i += size
            if len(value) != size: raise ValueError('Truncated field')
        elif wire == 2:
            size, i = _varint(b, i); value = b[i:i+size]; i += size
            if len(value) != size: raise ValueError('Truncated message')
        else: raise ValueError('Unsupported wire type')
        result.append((number, wire, value))
    return result


def message(b, path):
    for number in path:
        b = next(v for n, w, v in fields(b) if n == number and w == 2)
    return b


def quaternion_roll(q):
    q = np.asarray(q, float)
    if q.shape != (4,) or not np.isfinite(q).all() or not .98 <= np.linalg.norm(q) <= 1.02:
        raise ValueError('Invalid DJI attitude quaternion')
    matrix = Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix()
    # body->world, world Z vertical; image right/down correspond to body Y/Z.
    if np.hypot(matrix[2, 1], matrix[2, 2]) < .1:
        raise ValueError('Camera near vertical: image roll is ill-conditioned')
    return float(-np.degrees(np.arctan2(matrix[2, 1], matrix[2, 2])))


def extract_gyro(video, meta):
    """Only the inspected DJI AC206 schema is supported; never guess other devices."""
    rows = []
    with av.open(str(video)) as container:
        streams = [s for s in container.streams if s.metadata.get('handler_name') == 'CAM meta']
        if not streams: raise ValueError('No supported DJI CAM meta attitude track')
        protocol = None
        for packet in container.demux(streams[0]):
            if not packet.size: continue
            b = bytes(packet)
            if protocol is None:
                protocol = message(b, [1, 1, 1]).decode()
                if protocol != 'dvtm_ac206.proto':
                    raise ValueError(f'Unsupported telemetry schema: {protocol}')
            time = float(packet.pts * packet.time_base)
            qfields = {n: struct.unpack('<f', v)[0] for n, w, v in fields(message(b, [3, 2, 9])) if w == 5}
            q = [qfields.get(i, 0) for i in range(1, 5)]
            rows.append({'time': time, 'quaternion_wxyz': q, 'roll': quaternion_roll(q)})
    if len(rows) != meta['frames']:
        raise ValueError('Telemetry does not cover every source frame')
    for i, row in enumerate(rows):
        if abs(row['time'] - i/meta['fps']) > .25/meta['fps']:
            raise ValueError('Telemetry timestamps do not align with source frames')
        row['frame'] = i
    return {'source': 'DJI fused attitude (not raw gyro)', 'protocol': protocol,
            'mapping': 'body_to_world; image right=body Y, down=body Z; roll=-atan2(R32,R33)',
            'calibration': 'provisional axis mapping; visually checked, not device-calibrated', 'frames': rows}


def angular_difference(a, b):
    return float((a - b + 90) % 180 - 90)


def line_angle(line, width, height):
    if not isinstance(line, list) or len(line) != 4 or not all(isinstance(v, (float, int)) and math.isfinite(v) and 0 <= v <= 1000 for v in line):
        raise ValueError('Invalid visual reference line')
    x1,y1,x2,y2 = line
    if x2-x1 < 150: raise ValueError('Reference line must run left to right and span >=15% of image width')
    return float(np.degrees(np.arctan2((y2-y1)*height, (x2-x1)*width)))


def visual_candidates(image):
    h,w=image.shape[:2]
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),60,150)
    detected=cv2.HoughLinesP(edges,1,np.pi/720,70,minLineLength=w*.18,maxLineGap=25)
    if detected is None:return []
    lines=sorted(detected.reshape(-1,4),key=lambda l:-np.hypot(l[2]-l[0],l[3]-l[1]))
    result=[]
    for line in lines:
        x1,y1,x2,y2=map(float,line)
        if x2<x1:x1,y1,x2,y2=x2,y2,x1,y1
        if x2-x1<w*.35:continue
        slope=(y2-y1)/(x2-x1);angle=np.degrees(np.arctan(slope));center=y1+slope*(w/2-x1)
        if any(abs(angle-r['angle'])<3 and abs(center-r['center'])<h*.035 for r in result):continue
        result.append({'line':[x1/w*1000,y1/h*1000,x2/w*1000,y2/h*1000], 'angle':float(angle),'center':float(center)})
        if len(result)>=12:break
    return result


def visual_observation(c, meta, frame, model, api):
    out = Path(c['output_dir']); cache = out/'level_cache'; cache.mkdir(exist_ok=True)
    # Fresh CURRENT frame only: no identity references, history, or gyro numbers.
    image_path = Path(meta['cache'])/f'{frame:07d}.jpg'
    if image_path.exists(): image = cv2.imread(str(image_path))
    else:
        cap = cv2.VideoCapture(c['video']); cap.set(cv2.CAP_PROP_POS_FRAMES, frame); ok,image = cap.read();cap.release()
        if not ok: raise ValueError(f'Cannot decode level frame {frame}')
    width,height = meta['width'],meta['height']
    if image.shape[1] > 1280: image = cv2.resize(image,(1280,round(image.shape[0]*1280/image.shape[1])))
    ok,encoded = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])
    if not ok:raise ValueError('Image encoding failed')
    candidates=visual_candidates(image)
    annotated=image.copy()
    for index,candidate in enumerate(candidates):
        x1,y1,x2,y2=np.rint(np.array(candidate['line'])*([image.shape[1]/1000,image.shape[0]/1000]*2)).astype(int)
        cv2.line(annotated,(x1,y1),(x2,y2),(255,80,200),2)
        x=max(5,min(image.shape[1]-40,(x1+x2)//2));y=max(25,min(image.shape[0]-10,(y1+y2)//2))
        cv2.putText(annotated,str(index),(x,y),0,.9,(0,0,0),5);cv2.putText(annotated,str(index),(x,y),0,.9,(255,255,255),2)
    _,candidate_image=cv2.imencode('.jpg',annotated,[cv2.IMWRITE_JPEG_QUALITY,95])
    prompt = '''Image 1 is the unmodified CURRENT frame. Image 2 shows numbered detected line segments on that same frame.
Select the candidate_id of a segment that actually follows the distant level reference. Candidates include DISTRACTORS such as sails and waves: reject them. If none matches, use candidate_id=null and provide your own reference_line. For a selected candidate, the application uses its measured pixel geometry, not your approximate coordinates.
Measure the orientation of the CURRENT image independently. This is a fresh visual measurement, not a tracking task.
Choose a long background reference representing level: a true sea-sky horizon is best. A distant water/land boundary may provide an APPROXIMATE reference, but perspective or terrain can slope; label it shoreline and lower confidence. Never use sail edges, mast, rigging, foreground boat, waves, cloud edges or a ski slope as a horizontal reference.
Look carefully at the actual image: the line may rise OR fall toward the right. Mark two actual points on the SAME reference, one far LEFT and one far RIGHT. Do not invent a horizontal line, repeat a default angle, or assume the camera is level.
Coordinates are normalized 0..1000, top-left origin, y increases DOWNWARD. x2 must exceed x1 by at least 150. The application computes the angle from your points.
If no defensible reference exists, return reference_line=null and confidence=0.
Return ONLY JSON: {"candidate_id":integer or null,"reference_line":[x1,y1,x2,y2] or null,"cue":"horizon" or "shoreline" or "vertical_geometry" or "unknown","confidence":0.0 to 1.0,"direction":"rises_right" or "falls_right" or "horizontal" or "unknown","note":"describe the actual visible evidence and ambiguity"}.
For vertical_geometry return endpoints of the inferred HORIZONTAL reference, not the vertical feature. Shoreline estimates are visual approximations, not verified gravity.'''
    fingerprint = hashlib.sha256(encoded.tobytes()+json.dumps([model,prompt,VISUAL_VERSION,meta.get('signature'),meta['fps'],frame]).encode()).hexdigest()[:24]
    path = cache/f'{frame:07d}_{fingerprint}.json'
    if path.exists():
        cached=json.loads(path.read_text())
        if not cached.get('error'):return cached
    request = {'model':model,'temperature':0,'max_tokens':400,'messages':[{'role':'user','content':[
        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()}},
        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(candidate_image).decode()}},
        {'type':'text','text':prompt}]}]}
    data = {'frame':frame,'time':frame/meta['fps'],'model':model,'version':VISUAL_VERSION,'independent':True,'source_signature':meta.get('signature')}
    try:
        answer=api(c['api_url']+'/chat/completions',request)
        raw=answer['choices'][0]['message']['content'];value=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
        candidate_id=value.get('candidate_id')
        if candidate_id is not None and (type(candidate_id) is not int or not 0<=candidate_id<len(candidates)):raise ValueError('Invalid candidate ID')
        line=candidates[candidate_id]['line'] if candidate_id is not None else value.get('reference_line')
        score=float(value.get('confidence',0))
        if not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid level confidence')
        angle=None if line is None else line_angle(line,width,height)
        direction=value.get('direction','unknown')
        mismatch=angle is not None and ((angle>2 and direction=='rises_right') or (angle < -2 and direction=='falls_right'))
        cue=value.get('cue','unknown')
        if cue not in ('horizon','shoreline','vertical_geometry','unknown'):raise ValueError('Invalid cue')
        # Keep model score for auditing; confidence in an absolute level is lower for a shoreline.
        data.update(candidate_id=candidate_id,geometry_source='measured_line_selected_by_qwen' if candidate_id is not None else 'qwen_coordinates',candidates=candidates,reference_line=line,roll=angle,confidence=score,orientation_confidence=min(score,.6) if cue=='shoreline' else score,
            cue=cue,direction=direction,direction_mismatch=mismatch,note=value.get('note',''),raw=raw)
        if mismatch:data['orientation_confidence']=0
    except Exception as exc:data.update(roll=None,confidence=0,orientation_confidence=0,error=str(exc),note='Independent visual estimate failed')
    save(path,data);return data


def run_leveling(c, api, single=None):
    out=Path(c['output_dir']);meta=json.loads((out/'meta.json').read_text())
    gyro=extract_gyro(c['video'],meta);save(out/'gyro.json',gyro)
    served=api(c['api_url']+'/models')['data'][0];model=served['id']
    indices=meta['samples'] if single is None else [min(range(meta['frames']),key=lambda i:abs(i/meta['fps']-single))]
    path=out/'level_observations.json'
    prior=json.loads(path.read_text()) if path.exists() else []
    results={r['frame']:r for r in prior if r.get('version')==VISUAL_VERSION and r.get('model')==model and r.get('source_signature')==meta.get('signature')}
    with ThreadPoolExecutor(max_workers=int(c.get('level_workers',2))) as pool:
        pending={pool.submit(visual_observation,c,meta,i,model,api):i for i in indices}
        completed=0
        for future in as_completed(pending):
            row=future.result();results[row['frame']]=row;completed+=1
            save(path,sorted(results.values(),key=lambda r:r['frame']))
            save(out/'level_progress.json',{'completed':completed,'total':len(indices),'frame':row['frame'],'time':row['time'],'error':row.get('error')})
            print(f"Level {completed}/{len(indices)} t={row['time']:.2f} qwen={row.get('roll')} gyro={gyro['frames'][row['frame']]['roll']:.2f} cue={row.get('cue')} error={row.get('error')}",flush=True)
    return build_comparison(c,meta)


def build_comparison(c,meta):
    out=Path(c['output_dir']);gyro=extract_gyro(c['video'],meta);save(out/'gyro.json',gyro)
    path=out/'level_observations.json';observations=json.loads(path.read_text()) if path.exists() else []
    usable=[r for r in observations if r.get('roll') is not None and not r.get('error')]
    threshold=float(c.get('level_divergence_degrees',5))
    if not math.isfinite(threshold) or threshold<=0:raise ValueError('Level divergence threshold must be positive')
    by_frame={r['frame']:r for r in observations};frames=sorted(by_frame)
    comparison=[]
    rate=float(meta.get('analysis_fps',c.get('analysis_fps',1/meta.get('sample_interval',.5))))
    max_gap=max(.55/rate,1/meta['fps'])
    for g in gyro['frames']:
        i=g['frame'];j=min(frames,key=lambda k:abs(k-i)) if frames else None
        observation=by_frame[j] if j is not None and abs(j-i)/meta['fps']<=max_gap else None
        angle=observation.get('roll') if observation else None
        delta=angular_difference(angle,g['roll']) if angle is not None else None
        comparison.append({'frame':i,'time':g['time'],'gyro_roll':g['roll'],'final_roll':g['roll'],
            'level_source':'gyro','qwen_reference_line':observation.get('reference_line') if observation else None,'qwen_geometry_source':observation.get('geometry_source') if observation else None,'gyro_calibration':gyro['calibration'],
            'qwen_roll':angle,'qwen_level_frame':observation['frame'] if observation else None,
            'qwen_level_confidence':observation.get('orientation_confidence',0) if observation else None,
            'qwen_level_model_confidence':observation.get('confidence',0) if observation else None,
            'qwen_level_cue':observation.get('cue','unknown') if observation else 'unknown',
            'qwen_level_note':observation.get('note','') if observation else '',
            'qwen_level_error':observation.get('error') if observation else None,
            'qwen_direction_mismatch':observation.get('direction_mismatch',False) if observation else False,
            'level_difference':delta,'level_divergence_threshold':threshold,
            'level_divergent':delta is not None and abs(delta)>threshold})
    # Comparison uses nearest sampled visual estimate; never hides that offset in the UI.
    save(out/'level_comparison.json',comparison)
    differences=[abs(angular_difference(r['roll'],gyro['frames'][r['frame']]['roll'])) for r in usable]
    save(out/'level_summary.json',{'visual_samples':len(observations),'valid_visual_samples':len(usable),
        'distinct_reference_lines':len(set(tuple(r.get('reference_line') or []) for r in usable)),
        'mean_absolute_difference':float(np.mean(differences)) if differences else None,
        'divergent_frames':sum(r['level_divergent'] for r in comparison),'threshold_degrees':threshold,
        'repeated_visual_estimate_warning':len(usable)>10 and len(set(round(r['roll'],3) for r in usable))==1,
        'gyro_calibration':gyro['calibration']})
    return comparison
