#!/usr/bin/env python3
"""Local, resumable VL-assisted video reframing. See README.md for limitations."""
from verification_policy import target_description
from zoom_path import confident_frames, interpolate_zoom
from export_metadata import ffmpeg_metadata_args, write_sidecar
from tracking_selection import confidence_threshold

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import urllib.request

import cv2
import av
import imageio_ffmpeg
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter
from backward_tracking import backward_pass, confident
from temporal_context import build_context, context_key

PROMPT_VERSION = 5


def set_analysis_fps(c, value=None, source_fps=None):
    if value is None:
        value=c['analysis_fps'] if 'analysis_fps' in c else 1/c.get('sample_interval',.1)
    rate=float(value)
    if not math.isfinite(rate) or rate<=0:
        raise ValueError('Analysis FPS must be a finite positive number')
    if source_fps is not None and rate>source_fps+1e-6:
        raise ValueError(f'Analysis FPS cannot exceed the source rate ({source_fps:.5f})')
    c['analysis_fps']=rate;c['sample_interval']=1/rate
    return rate


def write_json(path, value):
    from durable_json import write_json as durable_write
    durable_write(path,value)


def api(url, payload=None):
    from lookout.events import emit
    import time
    started=time.monotonic();outcome='error';result=None
    try:
        result=_api_request(url,payload);outcome='success';return result
    finally:
        if url.endswith('/chat/completions'):
            usage=(result or {}).get('usage',{});choice=((result or {}).get('choices') or [{}])[0]
            emit('model',operation='completion',duration_ms=(time.monotonic()-started)*1000,outcome=outcome,
                 input_tokens=usage.get('prompt_tokens',0),output_tokens=usage.get('completion_tokens',0),
                 finish_reason=choice.get('finish_reason') or 'unknown')


def _api_request(url, payload=None):
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.load(r)


def image_message(path):
    return {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' +
            base64.b64encode(Path(path).read_bytes()).decode()}}


def load_config(path):
    c = json.loads((Path(__file__).resolve().parent.parent/'configs/defaults.json').read_text())
    from effective_config import merge
    c=merge(c,json.loads(Path(path).read_text()))
    c['api_url'] = os.environ.get('QWEN_API_URL',c['api_url']).rstrip('/')
    c['_config_path'] = str(Path(path).resolve())
    c['video'] = str((Path(path).resolve().parent / c['video']).resolve())
    c['output_dir'] = str((Path(path).resolve().parent / c['output_dir']).resolve())
    c['stage_store_dir']=str((Path(path).resolve().parent / c.get('stage_store_dir',os.environ.get('ACTION_REFRAME_STAGE_STORE',str(Path(c['output_dir'])/'.stage_records')))).resolve())
    c['ffmpeg'] = imageio_ffmpeg.get_ffmpeg_exe()
    from stage_records import configure
    configure(c)
    set_analysis_fps(c)
    from adaptive_verification import settings as adaptive_settings
    c['adaptive_verification']=adaptive_settings(c)
    from zoom_path import smoothing_settings
    c.update(smoothing_settings(c))
    from anchor_tracking import settings as anchor_settings
    c['anchor_tracking']=anchor_settings(c)
    if c.get('tracking_mode') not in ('single','dual','anchor'):
        raise ValueError('tracking_mode must be single, dual or anchor')
    if c.get('tracking_mode') in ('dual','anchor'):
        c['color_refinement']=False
        if c.get('tracking_render_path') not in ('raw_angle','leveled','selected'):
            raise ValueError('tracking_render_path must be raw_angle, leveled or selected')
    Path(c['output_dir']).mkdir(parents=True, exist_ok=True)
    return c


from lookout.events import timed as lookout_timed, count as lookout_count


@lookout_timed("preparation")
def prepare(c, max_time=None):
    out = Path(c['output_dir'])
    cap = cv2.VideoCapture(c['video'])
    if not cap.isOpened():
        raise RuntimeError('Cannot open video')
    fps = cap.get(cv2.CAP_PROP_FPS)
    set_analysis_fps(c,source_fps=fps)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(3)), int(cap.get(4))
    with av.open(c['video']) as container:
        probe={'format':{'duration':container.duration/av.time_base if container.duration is not None else None,
                         'tags':dict(container.metadata)},'streams':[]}
        for stream in container.streams:
            entry={'index':stream.index,'codec_type':stream.type,'tags':dict(stream.metadata),
                   'duration':float(stream.duration*stream.time_base) if stream.duration is not None else None}
            if stream.codec_context is not None:
                entry['codec_name']=stream.codec_context.name
            if stream.type=='video':
                entry.update(width=stream.width,height=stream.height,avg_frame_rate=str(stream.average_rate),
                             pix_fmt=stream.format.name if stream.format else None)
            probe['streams'].append(entry)
    write_json(out / 'source_metadata.json', probe)
    source = Path(c['video']).stat()
    signature = hashlib.sha256(json.dumps([c['video'], source.st_size, source.st_mtime_ns,
        c['reference_time'], c['reference_box'], c.get('reference_frames',[]), target_description(c), c['sample_interval'], PROMPT_VERSION]).encode()).hexdigest()[:16]
    cache = out / 'cache' / signature
    cache.mkdir(parents=True, exist_ok=True)
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(c['reference_time'] * fps))
    ok, frame = cap.read()
    if not ok:
        raise ValueError('Reference timestamp is outside the video')
    x1, y1, x2, y2 = map(int, c['reference_box'])
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError('Reference rectangle is outside the source image')
    crop = frame[y1:y2, x1:x2]
    scale = max(1, 320 / crop.shape[0])
    cv2.imwrite(str(cache / 'reference.jpg'), cv2.resize(crop, None, fx=scale, fy=scale))
    samples = sorted(set([int(round(t * fps)) for t in np.arange(0, n / fps, c['sample_interval'])] + [n-1]))
    last_sample = None if max_time is None else min(samples,key=lambda i:abs(i/fps-max_time))
    for i in samples:
        if c.get('tracking_mode')=='anchor':
            bounds=c.get('anchor_tracking',{})
            if i/fps<bounds.get('start_time',0)-1/fps or i/fps>bounds.get('end_time',n/fps)+1/fps:continue
        if last_sample is not None and i>last_sample:continue
        path = cache / f'{i:07d}.jpg'
        if path.exists():
            lookout_count('cache.hit')
            continue
        lookout_count('decode.seek');lookout_count('cache.miss')
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if not ok:
            raise RuntimeError(f'Failed decoding frame {i}')
        cv2.imwrite(str(path), f, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cap.release()
    meta = {'fps': fps, 'frames': n, 'width': w, 'height': h, 'cache': str(cache), 'samples': samples,
            'signature': signature, 'video': c['video'], 'analysis_fps':c['analysis_fps'],
            'sample_interval':c['sample_interval']}
    write_json(out / 'meta.json', meta)
    return meta


@lookout_timed("tracking.request")
def contextual_completion(c,meta,index,direction,history,model,images,prompt,max_tokens):
    meta=dict(meta)
    references=c.get('reference_frames',[])
    if any(not isinstance(i,int) or isinstance(i,bool) or not 0<=i<meta['frames'] for i in references):
        raise ValueError('reference_frames must contain valid zero-based source frame indices')
    meta['user_reference_frames']=references
    # Tracking history retains identity/motion but cannot anchor independent leveling.
    history=[{k:v for k,v in row.items() if k not in ('shoreline','level_confidence','level_note','manual_roll')} for row in history]
    settings=c.get('temporal_context',{})
    limit=min(int(settings.get('context_limit',32768)),int(c.get('_model_max_len',32768)))
    for compression in range(7):
        text,context_images,audit,folder=build_context(history,meta,index,direction,settings,
            lambda frame:cached_frame(c,meta,frame),compression)
        content=[image_message(path) for path in images]+[{'type':'text','text':text}]
        for entry in context_images:
            content.extend([{'type':'text','text':entry['label']},image_message(entry['path'])])
        content.append({'type':'text','text':prompt+'\nHistory estimates can be wrong. Explain significant object changes using current image evidence.'})
        messages=[{'role':'user','content':content}]
        request={'model':model,'messages':messages,'temperature':0,'max_tokens':max_tokens}
        if c.get('_structured_tracking'):request['response_format']={'type':'json_object'}
        # Use the server's actual multimodal tokenizer, not a character/token heuristic.
        tokenized=api(c['api_url'].removesuffix('/v1')+'/tokenize',{'model':model,'messages':messages})
        tokens=tokenized['count']
        audit.update(input_tokens=tokens,context_limit=limit,output_token_reserve=max_tokens)
        if tokens+max_tokens+256>limit:
            continue
        write_json(folder/f'request_c{compression}.json',{'audit':audit,'task_prompt':prompt,'history_text':text,
            'current_images':[str(path) for path in images]})
        validator=c.get('_stage_validator')
        if validator:
            from stage_records import configure,digest
            def compute(folder):
                response=api(c['api_url']+'/chat/completions',request)
                # Failed generations still reach the normal audited retry handler.
                choice=response['choices'][0]
                raw=choice['message']['content']
                if choice.get('finish_reason') in ('length','error','content_filter') or choice['message'].get('refusal'):
                    raise UncacheableResponse(response)
                try:
                    parsed,_=json.JSONDecoder().raw_decode(raw[raw.index('{'):])
                    validator(parsed)
                except (ValueError,KeyError,TypeError):raise UncacheableResponse(response)
                write_json(folder/'request.json',request)
                return response
            class UncacheableResponse(Exception):
                def __init__(self,response):self.response=response
            try:
                result,record=configure(c).run('discovery',1,dict(endpoint=c['api_url'],request_sha256=digest(request)),compute)
                audit['stage_record']=record
            except UncacheableResponse as error:result=error.response
        else:result=api(c['api_url']+'/chat/completions',request)
        audit['request_file']=str(folder/f'request_c{compression}.json')
        return result,audit
    raise RuntimeError('Current images and minimal temporal context exceed the configured context window')


def observe(c, meta, i, model, history=None):
    history=history or []
    cache = Path(meta['cache'])
    key=context_key(history,meta,i,'forward',c.get('temporal_context',{}))
    result_path = cache / f'{i:07d}_forward_{key}.json'
    if result_path.exists():
        cached = json.loads(result_path.read_text())
        if 'error' not in cached:
            return cached
    level_task = ('Leveling is supplied by gyro telemetry. Return shoreline=null, level_confidence=0 and level_note="separate leveling pass".'
                  if c.get('leveling_source')=='gyro' else
                  'Independently estimate visual level from the current frame using a true horizon or defensible background evidence. Do not assume shorelines or terrain are horizontal. Return two left-to-right reference points in shoreline, or null when ambiguous, with honest level_confidence.')
    prompt = f'''You are measuring a frame for an offline object-following video editor.
Image 1 is a close-up reference of the chosen target. Image 2 is the CURRENT full video frame.
Additional labeled images are temporal HISTORY, not the current frame.
Target description: {target_description(c)}
Identify only the user-selected subject described above; do not switch to foreground or similar objects.
Return the tight bounding box of ALL visible target parts and requested equipment. Exclude reflections.
If outside the frame, hidden, or not identifiable, return bbox=null; do not guess another object.
{level_task}
All coordinates are normalized integers 0..1000 relative to IMAGE 2 (top-left origin). NOT pixels.
Return ONLY JSON with these keys:
{{"bbox":[x1,y1,x2,y2] or null,"confidence":0.0 to 1.0,
"visibility":"visible" or "partial" or "absent" or "uncertain",
"shoreline":[x1,y1,x2,y2] or null,"level_confidence":0.0 to 1.0,
"level_note":"explain level direction and any change from prior frames","scene_cut":false,
"note":"short explanation of identity or uncertainty"}}
Current time: {i / meta['fps']:.3f} seconds.'''
    for attempt in range(3):
        try:
            answer,audit = contextual_completion(c,meta,i,'forward',history,model,
                [cache/'reference.jpg',cache/f'{i:07d}.jpg'],prompt,450)
            raw = answer['choices'][0]['message']['content']
            data = json.loads(raw[raw.index('{'):raw.rindex('}')+1])
            for key in ('bbox', 'shoreline'):
                b = data.get(key)
                if b is not None:
                    if len(b) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1000 for v in b):
                        raise ValueError(f'Invalid {key}')
                    if key == 'bbox' and not (b[0] < b[2] and b[1] < b[3]):
                        raise ValueError('Invalid rectangle')
            for key in ('confidence', 'level_confidence'):
                data[key] = float(np.clip(float(data.get(key, 0)), 0, 1))
            data.update(frame=i, time=i/meta['fps'], model=model, raw=raw,temporal_context=audit)
            write_json(result_path, data)
            return data
        except Exception as e:
            if attempt == 2:
                data = {'frame': i, 'time': i/meta['fps'], 'bbox': None, 'confidence': 0,
                        'visibility': 'uncertain', 'shoreline': None, 'level_confidence': 0,
                        'error': str(e), 'note': 'VL request failed'}
                write_json(result_path, data)
                return data
            time.sleep(2 ** attempt)


@lookout_timed("analysis")
def analyze(c, single=None):
    out = Path(c['output_dir'])
    meta = prepare(c,max_time=single)
    served=api(c['api_url'] + '/models')['data'][0];model=served['id'];c['_model_max_len']=served.get('max_model_len',32768)
    if c.get('tracking_mode') in ('anchor','dual'):
        from anchor_tracking import run_anchors
        return run_anchors(c,meta,model,(cached_frame,contextual_completion,write_json),api,single)
    from manual_tracking import manual_observations
    manual=manual_observations(c,meta)
    samples=sorted(set(meta['samples']) | set(manual))
    last=None if single is None else min(meta['samples'],key=lambda i:abs(i/meta['fps']-single))
    indices=samples if last is None else [i for i in samples if i<=last]
    results = []
    # Temporal dependence requires ordered inference; independent first-pass batching is no longer valid.
    for i in indices:
        r=dict(manual[i]) if i in manual else observe(c,meta,i,model,results)
        results.append(r)
        print(f"VL {len(results)}/{len(indices)} t={r['time']:.2f} box={r['bbox']} confidence={r['confidence']} history={r.get('temporal_context',{}).get('history_count',0)} {r.get('note','')}",flush=True)
        write_json(out/'analysis_progress.json',{'completed':len(results),'total':len(indices),'frame':i,
            'time':i/meta['fps'],'analysis_fps':c['analysis_fps'],'error':r.get('error')})
        if r.get('error'):
            raise RuntimeError(f"Forward analysis stopped at frame {i}: {r['error']}; cached earlier steps can be resumed")
    results.sort(key=lambda r: r['frame'])
    if single is None:
        if c.get('color_refinement',False):
            with ThreadPoolExecutor(max_workers=c['workers']) as pool:
                pending={pool.submit(recover_small,c,meta,r,model,[s for s in results if s['frame']<r['frame']]):r['frame'] for r in results
                         if not r.get('manual') and (r.get('bbox') is None or r.get('confidence',0)<confidence_threshold(c))}
                recovered={}
                for f in as_completed(pending):
                    r=f.result();recovered[r['frame']]=r
                    if r.get('recovered'):
                        print(f"Recovered t={r['time']:.2f} box={r['bbox']}",flush=True)
            results=[recovered.get(r['frame'],r) for r in results]
            # An isolated tiny color match is not enough evidence to switch identity.
            accepted=[]
            for r in results:
                if r.get('recovered'):
                    b=np.array(r['bbox']);center=(b[:2]+b[2:])/2
                    neighbors=[s for s in results if s is not r and s.get('bbox') is not None and s.get('confidence',0)>=confidence_threshold(c)
                               and abs(s['time']-r['time'])<=1.01
                               and np.linalg.norm((np.array(s['bbox'][:2])+s['bbox'][2:])/2-center)<100]
                    if not neighbors:
                        r=dict(r,recovery_candidate_bbox=r['bbox'],bbox=None,confidence=0,visibility='uncertain',recovered=False,
                               recovery_rejected='Isolated proposal lacks temporal identity confirmation')
                accepted.append(r)
            results=accepted
        write_json(out / 'observations_first_pass.json', results)
        if c.get('backward_recovery',True):
            results=run_backward(c,meta,results,model)
        write_json(out / 'observations.json', results)
    return results


def cached_frame(c,meta,index):
    path=Path(meta['cache'])/f'{index:07d}.jpg'
    if not path.exists():
        cap=cv2.VideoCapture(c['video']);cap.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,frame=cap.read();cap.release()
        if not ok:raise RuntimeError(f'Cannot decode backward frame {index}')
        cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,92])
    image=cv2.imread(str(path))
    if image is None:raise RuntimeError(f'Cannot read cached frame {index}')
    return image


def backward_observe(c,meta,current,seed,model,history=None):
    """Condition Qwen on the immediately later accepted crop and motion-guided search region."""
    history=history or [seed]
    version=4
    fingerprint=hashlib.sha256(json.dumps([version,model,target_description(c),meta['signature'],
        current['frame'],seed['frame'],seed['bbox'],seed['confidence'],c.get('color_refinement',False),c.get('target_hue'),
        context_key(history,meta,current['frame'],'backward',c.get('temporal_context',{}))],sort_keys=True).encode()).hexdigest()[:20]
    cache=Path(meta['cache'])/'backward';cache.mkdir(exist_ok=True)
    path=cache/(fingerprint+'.json')
    if path.exists():
        data=json.loads(path.read_text())
        if not data.get('error'):return data
    try:
        later=cached_frame(c,meta,seed['frame']);earlier=cached_frame(c,meta,current['frame'])
        h,w=earlier.shape[:2];box=np.array(seed['bbox'])*[w/1000,h/1000,w/1000,h/1000]
        predicted=box.copy();motion=False
        # Estimate camera motion from a broad band around the later target. The VL model
        # still confirms identity; this only places a search window in the earlier frame.
        scale=960/w
        a=cv2.cvtColor(cv2.resize(later,(960,round(h*scale))),cv2.COLOR_BGR2GRAY)
        b=cv2.cvtColor(cv2.resize(earlier,(960,round(h*scale))),cv2.COLOR_BGR2GRAY)
        mask=np.zeros_like(a);cy=(box[1]+box[3])/2*scale
        mask[max(0,int(cy-100)):min(a.shape[0],int(cy+100)),:]=255
        points=cv2.goodFeaturesToTrack(a,250,.01,8,mask=mask)
        if points is not None and len(points)>=10:
            dest,status,_=cv2.calcOpticalFlowPyrLK(a,b,points,None,winSize=(31,31),maxLevel=4)
            if dest is not None:
                back,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,dest,None,winSize=(31,31),maxLevel=4)
                if back is not None:
                    valid=(status.ravel()==1)&(back_status.ravel()==1)&(np.linalg.norm(back.reshape(-1,2)-points.reshape(-1,2),axis=1)<2)
                    if valid.sum()>=10:
                        matrix,inliers=cv2.estimateAffinePartial2D(points.reshape(-1,2)[valid],dest.reshape(-1,2)[valid],method=cv2.RANSAC,ransacReprojThreshold=3)
                        if matrix is not None and inliers.sum()>=8 and .7<np.linalg.norm(matrix[0,:2])<1.4:
                            p=corners(box)*scale@matrix[:,:2].T+matrix[:,2]
                            predicted=np.r_[p.min(axis=0),p.max(axis=0)]/scale;motion=True
        center=(predicted[:2]+predicted[2:])/2
        half=np.maximum((predicted[2:]-predicted[:2])*2.5,[100,100])
        if not motion:half=np.maximum(half,[w*.18,h*.18])
        region=np.r_[np.maximum(center-half,[0,0]),np.minimum(center+half,[w,h])].astype(int)
        xa,ya,xb,yb=region
        if xb<=xa or yb<=ya:raise ValueError('Predicted target lies outside the earlier frame')
        x1,y1,x2,y2=box;pad=max(12,(y2-y1)*.25)
        seed_crop=later[max(0,int(y1-pad)):min(h,int(y2+pad)),max(0,int(x1-pad)):min(w,int(x2+pad))]
        if not seed_crop.size:raise ValueError('Empty seed crop')
        seed_path=cache/(fingerprint+'_seed.jpg');search_path=cache/(fingerprint+'_search.jpg')
        seed_scale=400/max(seed_crop.shape[:2]);cv2.imwrite(str(seed_path),cv2.resize(seed_crop,None,fx=seed_scale,fy=seed_scale))
        search=earlier[ya:yb,xa:xb];search_scale=900/max(search.shape[:2])
        proposals=[]
        if c.get('color_refinement',False):
            reference=cv2.imread(str(Path(meta['cache'])/'reference.jpg'))
            refhsv=cv2.cvtColor(reference,cv2.COLOR_BGR2HSV)
            saturated=(refhsv[:,:,1]>110)&(refhsv[:,:,2]>120)
            if saturated.any():
                hue=float(c.get('target_hue',np.median(refhsv[:,:,0][saturated])));hsv=cv2.cvtColor(search,cv2.COLOR_BGR2HSV)
                diff=np.abs(hsv[:,:,0].astype(float)-hue);diff=np.minimum(diff,180-diff)
                mask=((diff<17)&(hsv[:,:,1]>65)&(hsv[:,:,2]>100)).astype('uint8')
                mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
                _,_,stats,_=cv2.connectedComponentsWithStats(mask)
                components=sorted([s for s in stats[1:] if s[4]>=3 and s[3]>=3 and s[3]>s[2]*.65],key=lambda s:s[4],reverse=True)[:8]
                for x,y,bw,bh,area in components:
                    # Sail pixels supply geometry; padding retains the adjacent hull/sailor.
                    proposals.append([max(0,x-bw*.5-3),max(0,y-2),min(xb-xa,x+bw*1.5+3),min(yb-ya,y+bh*1.25+4)])
        display=cv2.resize(search,None,fx=search_scale,fy=search_scale)
        for k,proposal in enumerate(proposals):
            left,top,right,bottom=(np.array(proposal)*search_scale).astype(int)
            cv2.rectangle(display,(left,top),(right,bottom),(255,90,20),2)
            cv2.putText(display,str(k),(left,max(20,top-5)),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),3)
            cv2.putText(display,str(k),(left,max(20,top-5)),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),1)
        cv2.imwrite(str(search_path),display)
        prompt=f'''Track the SAME object BACKWARD in time, using visible evidence.
Image 1: original user-selected identity reference.
Image 2: crop of a CONFIRMED later detection at {seed['time']:.3f} seconds.
Image 3: enlarged search region in the EARLIER frame at {current['time']:.3f} seconds.
Image 4: CURRENT EARLIER full frame. Additional labeled images are temporal HISTORY.
Target: {target_description(c)}
The time gap is {seed['time']-current['time']:.3f} seconds. Camera and subject may move.
Use the later appearance to find the same target in Image 3, including all visible parts.
Do not merely copy its later coordinates, assume it is present, select reflections or switch to a similar object.
If it is hidden, outside this search region, too small to identify, or there is a scene cut, say uncertain/absent.
Return ONLY JSON: {{"bbox":[x1,y1,x2,y2] or null,"confidence":0..1,
"visibility":"visible" or "partial" or "absent" or "uncertain","scene_cut":false,"note":"brief evidence",
"shoreline":[x1,y1,x2,y2] or null,"level_confidence":0..1,"level_note":"background level evidence and change from later frames"}}.
Bounding box coordinates are normalized 0..1000 within IMAGE 3 ONLY.
Shoreline coordinates MUST be normalized 0..1000 within FULL IMAGE 4. Estimate its signed slope from the actual background,
using only the current background evidence. Do not use the sail or rigging as a level reference.'''
        if c.get('leveling_source')=='gyro':
            prompt+='\nLeveling is supplied by gyro telemetry. For this tracking request return shoreline=null, level_confidence=0, level_note="separate leveling pass".'
        if c.get('color_refinement',False):
            prompt+=f'''\nImage 3 has {len(proposals)} NUMBERED candidate rectangles, with ids starting at 0.
Select the rectangle containing the SAME target. Add "candidate": integer or null to your JSON.
The rectangle coordinates are measured from image pixels, so selecting the correct candidate is more important than reporting a bbox.
Do not select a colored background feature or the camera boat. If none matches or there are no candidates, candidate=null and visibility=uncertain.'''
        response,audit=contextual_completion(c,meta,current['frame'],'backward',history,model,
            [Path(meta['cache'])/'reference.jpg',seed_path,search_path,Path(meta['cache'])/f"{current['frame']:07d}.jpg"],prompt,450)
        raw=response['choices'][0]['message']['content'];data=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
        score=data.get('confidence')
        if not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid backward confidence')
        if c.get('color_refinement',False):
            k=data.get('candidate');data['model_bbox']=data.get('bbox')
            if isinstance(k,int) and not isinstance(k,bool) and 0<=k<len(proposals):
                data['bbox']=(np.array(proposals[k])/[xb-xa,yb-ya,xb-xa,yb-ya]*1000).tolist()
                data['geometry_source']='color component selected by Qwen'
            else:
                data.update(bbox=None,visibility='uncertain')
        if data.get('bbox') is not None:
            probe=dict(data,confidence=1,visibility='visible')
            if not confident(probe,0):raise ValueError('Invalid backward rectangle/visibility')
            local_box=np.array(data['bbox'],float)
            full_box=local_box/1000*[xb-xa,yb-ya,xb-xa,yb-ya]+[xa,ya,xa,ya]
            data['crop_bbox']=data['bbox'];data['bbox']=(full_box/[w,h,w,h]*1000).tolist()
            ratio=(full_box[2:]-full_box[:2])/np.maximum(box[2:]-box[:2],2)
            if np.any(ratio>4) or np.any(ratio<.2):
                data.update(visibility='uncertain',note='Rejected abrupt size change: '+data.get('note',''))
        data.update(raw=raw,model=model,search_region_pixels=region.tolist(),camera_motion_estimated=motion,
                    frame=current['frame'],time=current['time'],temporal_context=audit)
    except Exception as e:
        data={'bbox':None,'confidence':0,'visibility':'uncertain','error':str(e),'note':'Backward tracking failed'}
    write_json(path,data)
    return data


def run_backward(c,meta,observations,model):
    out=Path(c['output_dir']);working={r['frame']:dict(r) for r in observations}
    corrections_path=out/'corrections.json'
    corrections=json.loads(corrections_path.read_text()) if corrections_path.exists() else {}
    for key,correction in corrections.items():
        if 'bbox' not in correction:continue
        i=int(key);r=working.get(i,{'frame':i,'time':i/meta['fps'],'shoreline':None,'level_confidence':0})
        box=correction['bbox']
        working[i]=dict(r,bbox=None if box is None else (np.array(box)/[meta['width'],meta['height'],meta['width'],meta['height']]*1000).tolist(),
                        confidence=0 if box is None else 1,visibility='absent' if box is None else 'visible',manual=True,analysis_source='manual')
    def attempt(current,seed,history):
        r=backward_observe(c,meta,current,seed,model,history)
        print(f"Backward {seed['time']:.2f}s -> {current['time']:.2f}s confidence={r.get('confidence',0)} visibility={r.get('visibility')} {r.get('note','')}",flush=True)
        return r
    results,report=backward_pass(list(working.values()),attempt,threshold=confidence_threshold(c),with_history=True)
    report.update(sample_interval=c['sample_interval'],fps=meta['fps'])
    write_json(out/'backward_report.json',report)
    print(f"Backward pass: recovered {report['recovered_samples']} of {report['attempted_samples']} attempted samples",flush=True)
    return results


def recover_small(c,meta,r,model,history=None):
    """Look closely at small sail-colored shoreline proposals missed by the full-frame VL pass."""
    history=history or []
    cache=Path(meta['cache']);key=context_key(history,meta,r['frame'],'forward',c.get('temporal_context',{}))
    path=cache/f"{r['frame']:07d}_recovery_h{c.get('target_hue','auto')}_{key}.json"
    if path.exists():return json.loads(path.read_text())
    frame=cv2.imread(str(cache/f"{r['frame']:07d}.jpg"));h,w=frame.shape[:2]
    shore=r.get('shoreline')
    if shore is None:return r
    a=np.array(shore)*[w/1000,h/1000,w/1000,h/1000]
    if abs(a[2]-a[0])<100:return r
    slope=(a[3]-a[1])/(a[2]-a[0])
    ref=cv2.imread(str(cache/'reference.jpg'));refhsv=cv2.cvtColor(ref,cv2.COLOR_BGR2HSV)
    sat=(refhsv[:,:,1]>110)&(refhsv[:,:,2]>120)
    if not sat.any():return r
    hue=float(c.get('target_hue',np.median(refhsv[:,:,0][sat])));hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    d=np.abs(hsv[:,:,0].astype(float)-hue);d=np.minimum(d,180-d)
    mask=((d<17)&(hsv[:,:,1]>65)&(hsv[:,:,2]>100)).astype('uint8')
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    proposals=[]
    for x,y,bw,bh,area in stats[1:]:
        if not (3<=area<3000 and 3<=bh<120 and bh>=bw*1.15):continue
        residual=abs(y+bh-(a[1]+slope*(x+bw/2-a[0])))
        if residual>h*.075:continue
        proposals.append((area/(1+residual*.03),x,y,bw,bh))
    proposals=sorted(proposals,reverse=True)[:4]
    if not proposals:
        write_json(path,r);return r
    regions=[];tiles=[]
    for k,(_,x,y,bw,bh) in enumerate(proposals):
        radius=max(35,int(bh*1.5));cx,cy=x+bw/2,y+bh/2
        xa,ya=max(0,int(cx-radius)),max(0,int(cy-radius));xb,yb=min(w,int(cx+radius)),min(h,int(cy+radius))
        regions.append((xa,ya,xb,yb))
        tile=cv2.resize(frame[ya:yb,xa:xb],(400,400))
        tile=cv2.copyMakeBorder(tile,30,0,0,0,cv2.BORDER_CONSTANT)
        cv2.putText(tile,f'Candidate {k}',(8,23),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2);tiles.append(tile)
    montage=cache/f"{r['frame']:07d}_candidates.jpg";cv2.imwrite(str(montage),np.hstack(tiles))
    prompt=f'''Image 1 is the target reference. Image 2 contains numbered enlarged candidate crops from a distant shoreline.
Target: {target_description(c)}
Look carefully at the tiny lime-green sail. Select a candidate only if it is plausibly the same separate sailing dinghy,
not a buoy, roof, tree, windsurfer, or piece of the foreground camera boat. If too ambiguous, select null.
Return ONLY JSON {{"candidate": integer or null, "confidence":0..1, "bbox":[x1,y1,x2,y2] or null,"note":"brief reason"}}.
bbox encloses the entire visible sail, hull and sailor within the SELECTED candidate's 400x400 square,
excluding the 30-pixel label strip, with coordinates normalized to 0..1000 within that square.'''
    try:
        response,audit=contextual_completion(c,meta,r['frame'],'forward',history,model,
            [cache/'reference.jpg',montage],prompt,220)
        raw=response['choices'][0]['message']['content'];v=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
        k=v.get('candidate');b=v.get('bbox')
        if isinstance(k,int) and 0<=k<len(regions) and v.get('confidence',0)>=confidence_threshold(c) and b is not None:
            b=np.array(b,float)
            if b.shape!=(4,) or not np.isfinite(b).all() or not (0<=b[0]<b[2]<=1000 and 0<=b[1]<b[3]<=1000):raise ValueError('Invalid recovery rectangle')
            xa,ya,xb,yb=regions[k]
            b=b/1000*[xb-xa,yb-ya,xb-xa,yb-ya]+[xa,ya,xa,ya]
            r=dict(r,bbox=(b/[w,h,w,h]*1000).tolist(),confidence=min(float(v['confidence']),.8),visibility='visible',
                   recovered=True,recovery_note=v.get('note'),recovery_raw=raw,recovery_temporal_context=audit)
        write_json(path,r)
    except Exception as e:
        r=dict(r,recovery_error=str(e))
    return r


def corners(box):
    x1, y1, x2, y2 = box
    return np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], dtype=np.float64)


def refine_level(frame, shore):
    """Robust long shoreline edges near the semantic hint; never use the target mast."""
    if shore is None:
        return 0., False
    h, w = frame.shape[:2]
    a = np.array(shore, dtype=float) * [w/1000,h/1000,w/1000,h/1000]
    x1,y1,x2,y2 = a
    if abs(x2-x1) < w*.15:
        return 0., False
    slope = (y2-y1)/(x2-x1)
    angle = math.degrees(math.atan(slope))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 140)
    yy,xx = np.ogrid[:h,:w]
    edges[np.abs(yy-(y1+slope*(xx-x1))) > h*.025] = 0
    lines = cv2.HoughLinesP(edges, 1, np.pi/720, 35, minLineLength=w*.10, maxLineGap=15)
    angles, weights = [], []
    if lines is not None:
        for line in lines.reshape(-1,4):
            dx,dy = line[2]-line[0],line[3]-line[1]
            if dx == 0:
                continue
            v = math.degrees(math.atan(dy/dx))
            if abs(v-angle) < 7:
                angles.append(v); weights.append(math.hypot(dx,dy))
    if not angles:
        return angle, False
    order = np.argsort(angles)
    vals, ws = np.array(angles)[order], np.array(weights)[order]
    return float(vals[np.searchsorted(np.cumsum(ws), np.sum(ws)*.5)]), True


def color_component(frame, box, hue):
    """Optional clip-specific refinement, gated by VL identity and location."""
    h,w = frame.shape[:2]
    x1,y1,x2,y2 = box
    bw,bh = max(x2-x1,2),max(y2-y1,2)
    xa,ya = max(0,int(x1-bw*.45-8)),max(0,int(y1-bh*.30-8))
    xb,yb = min(w,int(x2+bw*.45+8)),min(h,int(y2+bh*.30+8))
    if xb<=xa or yb<=ya:
        return None
    hsv = cv2.cvtColor(frame[ya:yb,xa:xb], cv2.COLOR_BGR2HSV)
    diff = np.abs(hsv[:,:,0].astype(float)-hue)
    diff = np.minimum(diff,180-diff)
    mask = ((diff<14)&(hsv[:,:,1]>100)&(hsv[:,:,2]>105)).astype('uint8')
    count,labels,stats,centers = cv2.connectedComponentsWithStats(mask)
    best,score = None, float('inf')
    for k in range(1,count):
        x,y,cw,ch,area = stats[k]
        if area<3 or ch<3 or ch>bh*1.7 or cw>bw*1.8:
            continue
        cx,cy = centers[k]+[xa,ya]
        dist = ((cx-(x1+x2)/2)/max(bw,15))**2 + ((cy-(y1+y2)/2)/max(bh,15))**2
        s = dist - .08*math.log(area)
        if s<score:
            score=s;best=np.array([x+xa,y+ya,x+xa+cw,y+ya+ch],float)
    return best


def measurements(c, meta, observations):
    n,w,h,fps = meta['frames'],meta['width'],meta['height'],meta['fps']
    out=Path(c['output_dir'])
    corrections_path=out/'corrections.json'
    corrections=json.loads(corrections_path.read_text()) if corrections_path.exists() else {}
    obs={r['frame']:dict(r) for r in observations}
    for key,val in corrections.items():
        i=int(key)
        r=obs.get(i,{'frame':i,'time':i/fps,'shoreline':None,'level_confidence':0})
        if 'bbox' in val:
            r.update(bbox=None if val['bbox'] is None else (np.array(val['bbox'])/[w,h,w,h]*1000).tolist(),
                     confidence=1 if val['bbox'] is not None else 0, visibility='visible' if val['bbox'] else 'absent',manual=True)
        if 'roll' in val:
            r.update(manual_roll=float(val['roll']),level_confidence=1)
        obs[i]=r
    observations=sorted(obs.values(),key=lambda x:x['frame'])
    ix=np.array([r['frame'] for r in observations])
    from verification_policy import accepted_row
    from motion_render import motion_usable
    valid=np.array([motion_usable(r) or (accepted_row(r,confidence_threshold(c)) if r.get('box_verification',{}).get('version',0)>=7 else
        r.get('bbox') is not None and r.get('confidence',0)>=confidence_threshold(c) and r.get('visibility') not in ('absent','uncertain')) for r in observations])
    if not valid.any():
        raise RuntimeError('No reliable target observations. Use the review UI to supply a correction.')
    boxes=np.array([r['bbox'] for r,v in zip(observations,valid) if v])*[w/1000,h/1000,w/1000,h/1000]
    grid=np.arange(n)
    expected=np.column_stack([np.interp(grid,ix[valid],boxes[:,j]) for j in range(4)])
    nearest=np.abs(grid[:,None]-ix).argmin(axis=1)
    supported=valid[nearest] & (np.abs(grid-ix[nearest])<=fps*max(c['sample_interval'],.6))
    raw=expected.copy()
    flags=[[] for _ in range(n)]
    roll=np.zeros(n); level_ok=np.zeros(n,dtype=bool)
    shores=np.array([r.get('shoreline') if r.get('shoreline') is not None else [np.nan]*4 for r in observations],float)
    good=np.isfinite(shores).all(axis=1)
    if good.any():
        shore_per_frame=np.column_stack([np.interp(grid,ix[good],shores[good,j]) for j in range(4)])
    else:
        shore_per_frame=np.full((n,4),np.nan)
    ref=cv2.imread(str(Path(meta['cache'])/'reference.jpg'))
    hsv=cv2.cvtColor(ref,cv2.COLOR_BGR2HSV)
    sat=(hsv[:,:,1]>110)&(hsv[:,:,2]>120)
    hue=float(c.get('target_hue',np.median(hsv[:,:,0][sat]))) if sat.any() else None
    # Color refinement is deliberately opt-in: it is appropriate for this sail, not arbitrary objects.
    use_color=c.get('color_refinement',False) and hue is not None
    cap=cv2.VideoCapture(c['video'])
    last_level=0.
    for i in range(n):
        ok,frame=cap.read()
        if not ok:
            raise RuntimeError(f'Decode ended at {i}/{n}')
        near=observations[nearest[i]]
        flags[i].extend(near.get('selection_flags',[]))
        if near.get('recovered'):
            flags[i].append('recovered_small_target_verify_identity')
        if near.get('recovery_rejected'):
            flags[i].append('reidentification_needs_label')
        if not supported[i]:
            flags[i].append('target_missing_or_uncertain')
        elif use_color:
            component=color_component(frame,expected[i],hue)
            if component is not None:
                # Preserve the model's hull/sail extent while refining the sail's center and top.
                e=expected[i];b=component
                raw[i]=[min(e[0],b[0]),min(e[1],b[1]),max(e[2],b[2]),max(e[3],b[3])]
                shift=(b[:2]+b[2:])/2-(e[:2]+e[2:])/2
                raw[i,[0,2]]+=np.clip(shift[0]*.55,-(e[2]-e[0])*.3,(e[2]-e[0])*.3)
                raw[i,0]=min(raw[i,0],b[0]);raw[i,2]=max(raw[i,2],b[2])
            else:
                flags[i].append('appearance_not_confirmed')
        if supported[i] and min(raw[i,2]-raw[i,0],raw[i,3]-raw[i,1])<12:
            flags[i].append('very_small_target')
        if supported[i] and (raw[i,0]<3 or raw[i,1]<3 or raw[i,2]>w-3 or raw[i,3]>h-3):
            flags[i].append('target_at_source_edge')
        if near.get('visibility')=='partial':
            flags[i].append('partial_visibility')
        if near.get('error'):
            flags[i].append('vl_error')
        if np.isfinite(shore_per_frame[i]).all():
            small=cv2.resize(frame,(960,round(h*960/w)))
            angle,good_edge=refine_level(small,shore_per_frame[i])
            last_level=angle
            level_ok[i]=good_edge and near.get('level_confidence',0)>=.65
        roll[i]=last_level
        if not level_ok[i]:
            flags[i].append('level_needs_review')
        if i%300==0:
            print(f'Measure {i}/{n}',flush=True)
    cap.release()
    roll=gaussian_filter1d(median_filter(roll,size=5),max(1,fps*.08))
    manual_levels=[(r['frame'],r['manual_roll']) for r in observations if 'manual_roll' in r]
    if manual_levels:
        # Apply correction deltas smoothly between explicit leveling keyframes.
        mi=np.array([r[0] for r in manual_levels]);mv=np.array([r[1] for r in manual_levels])
        roll+=np.interp(grid,mi,mv-roll[mi])
    return raw,supported,roll,flags


def camera_path(c,meta,boxes,supported,roll,zoom_anchors=None):
    n,w,h,fps=meta['frames'],meta['width'],meta['height'],meta['fps']
    ow,oh=c['output_width'],c['output_height']
    centers=(boxes[:,:2]+boxes[:,2:])/2
    desired=np.zeros(n)
    for i in range(n):
        r=cv2.getRotationMatrix2D((0,0),float(roll[i]),1)[:,:2]
        pts=corners(boxes[i])@r.T
        bw,bh=np.ptp(pts,axis=0)
        desired[i]=max(bh/c['subject_height_fraction'],bw*oh/ow/(1-2*c['margin_fraction']),24)
    # Framing position keeps its existing hold-and-return behavior during gaps.
    last=None
    for i in range(n):
        if supported[i]:
            last=i
        elif last is None:
            centers[i]=[w/2,h/2]
        else:
            dt=(i-last)/fps
            blend=np.clip((dt-c['hold_seconds'])/c['widen_seconds'],0,1)
            centers[i]=centers[last]*(1-blend)+np.array([w/2,h/2])*blend
    sigma=max(1,c['smoothing_seconds']*fps)
    centers=gaussian_filter1d(centers,sigma,axis=0)
    # Fit confident anchors after center smoothing; allow source-exterior borders.
    minimum=np.zeros(n)
    for i in range(n):
        if not supported[i]:
            continue
        r=cv2.getRotationMatrix2D((0,0),float(roll[i]),1)[:,:2]
        p=(corners(boxes[i])-centers[i])@r.T
        minimum[i]=max(2*np.abs(p[:,1]).max(),2*np.abs(p[:,0]).max()*oh/ow)/(1-2*c['margin_fraction'])
    if zoom_anchors is None:
        zoom_anchors=np.flatnonzero(supported)
    extent=interpolate_zoom(np.maximum(desired,minimum),h,zoom_anchors,endpoint_zoom=1.)
    from zoom_path import constrain_zoom
    extent,required,_,_=constrain_zoom(extent,centers,roll,(w,h),(ow,oh),minimum,c.get('minimum_crop_short_side',180))
    from zoom_path import smooth_zoom,smoothing_settings
    options=smoothing_settings(c)
    extent=smooth_zoom(extent,required,fps,options['zoom_seconds_per_doubling'],options['zoom_smoothing_seconds'])
    return centers,extent


def composite(frame,matrix,size,feather,box=None):
    ow,oh=size
    sharp=cv2.warpAffine(frame,matrix,(ow,oh),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    mask=cv2.warpAffine(np.ones(frame.shape[:2],np.uint8)*255,matrix,(ow,oh),flags=cv2.INTER_NEAREST,
                        borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    if np.all(mask):
        return sharp
    # Padded distance handles borders touching the output edge consistently.
    dist=cv2.distanceTransform(np.pad(mask,1),cv2.DIST_L2,3)[1:-1,1:-1]
    alpha=np.clip(dist/max(feather,1),0,1)
    alpha=alpha*alpha*(3-2*alpha)
    if box is not None:
        p=corners(box)@matrix[:,:2].T+matrix[:,2]
        protect=np.zeros((oh,ow),np.uint8)
        cv2.fillConvexPoly(protect,np.rint(p).astype('int32'),255)
        alpha=np.maximum(alpha,(protect/255.)*(mask/255.))
    small=cv2.resize(sharp,(max(1,ow//8),max(1,oh//8)))
    blur=cv2.resize(cv2.GaussianBlur(small,(0,0),5),(ow,oh))
    return np.clip(sharp*alpha[:,:,None]+blur*(1-alpha[:,:,None]),0,255).astype('uint8')


@lookout_timed("render")
def render(c):
    out=Path(c['output_dir'])
    if (out/'anchor_checkpoint.json').exists():
        from result_shards import export_snapshot
        export_snapshot(out,write_json)
    meta=json.loads((out/'meta.json').read_text())
    c=dict(c)
    from zoom_path import output_dimensions
    c['output_width'],c['output_height']=output_dimensions(c,meta)
    # Render with the observations' cadence, even if the next run's setting changed.
    set_analysis_fps(c,meta.get('analysis_fps',1/meta.get('sample_interval',.5)))
    from effective_config import save as save_effective_config
    save_effective_config(c,'render')
    observation_path=out/(f"tracking_{c['tracking_render_path']}.json" if c.get('tracking_mode')=='dual' else 'observations.json')
    observations=json.loads(observation_path.read_text())
    if c.get('tracking_mode')=='dual':
        write_json(out/'observations.json',observations)
    from motion_render import merge_motion
    observations=merge_motion(observations,meta,out,confidence_threshold(c))
    from path_candidates import apply_to_render
    observations=apply_to_render(observations,out,confidence_threshold(c))
    boxes,supported,roll,flags=measurements(c,meta,observations)
    level_rows=None
    if c.get('leveling_source')=='gyro':
        from leveling import build_comparison
        level_rows=build_comparison(c,meta)
        roll=np.array([row['final_roll'] for row in level_rows])
        for i,row in enumerate(level_rows):
            flags[i]=[flag for flag in flags[i] if flag!='level_needs_review']
            if row['level_divergent']:flags[i].append('qwen_gyro_divergence')
            if row['qwen_roll'] is not None and (row['qwen_level_confidence'] or 0)<.65:flags[i].append('visual_level_uncertain')
            if row['qwen_direction_mismatch']:flags[i].append('visual_level_direction_inconsistent')
        # Manual roll keys cannot silently override an explicitly selected gyro final source.
    corrections_path=out/'corrections.json'
    corrections=json.loads(corrections_path.read_text()) if corrections_path.exists() else {}
    zoom_anchors=confident_frames(observations,corrections,meta['frames'],confidence_threshold(c))
    from stage_records import configure,array_id
    store=configure(c)
    inputs=dict(boxes=array_id(boxes),supported=array_id(supported),roll=array_id(roll),anchors=list(map(int,zoom_anchors)),
        video={k:meta[k] for k in ('frames','width','height','fps')},
        settings={k:c[k] for k in ('output_width','output_height','subject_height_fraction','margin_fraction','hold_seconds','widen_seconds','smoothing_seconds')})
    def compute_camera(folder):
        centers,extent=camera_path(c,meta,boxes,supported,roll,zoom_anchors)
        return dict(centers=centers.tolist(),extent=extent.tolist())
    inputs['settings']['minimum_crop_short_side']=c.get('minimum_crop_short_side',180)
    from zoom_path import smoothing_settings
    inputs['settings'].update(smoothing_settings(c))
    from render_planner import settings as planner_settings,polygons as planner_polygons,background_motion,plan as plan_render,VERSION as PLANNER_VERSION,CAMERA_PATH_VERSION
    planner=planner_settings(c)
    if planner['enabled']:
        polygon_rows,absent=planner_polygons(observations,corrections,boxes,supported,meta)
        polygon_data=[None if poly is None else poly.tolist() for poly in polygon_rows]
        gyro=json.loads((out/'gyro.json').read_text()) if c.get('leveling_source')=='gyro' else None
        # The image estimator operates after the same leveling applied by rendering.
        motion_gyro=gyro or dict(frames=[dict(roll=float(a)) for a in roll])
        video_stat=Path(c['video']).stat()
        motion_inputs=dict(video=str(Path(c['video']).resolve()),size=video_stat.st_size,mtime_ns=video_stat.st_mtime_ns,
            polygons=polygon_data,roll=array_id(roll),settings=planner)
        motion,motion_record=store.run('render_camera_motion',PLANNER_VERSION,motion_inputs,
            lambda folder:background_motion(c['video'],meta,polygon_rows,motion_gyro,planner))
        write_json(out/'camera_motion.json',dict(**motion,stage_record=motion_record))
        observed={r['frame']:r for r in observations}
        margins=[min(.3,c['margin_fraction']+(0 if str(i) in corrections or observed.get(i,{}).get('identity_verified') else .05)) for i in range(meta['frames'])]
        planning_config=dict(c,_render_margins=margins)
        inputs.update(polygons=polygon_data,absent=absent,planner=planner,motion_key=motion_record['key'],margins=margins)
        camera,camera_record=store.run('camera_path',CAMERA_PATH_VERSION,inputs,lambda folder:plan_render(planning_config,meta,polygon_rows,absent,roll,motion))
        write_json(out/'camera_path_review.json',dict(settings=planner,imu_calibration=camera['imu_calibration'],frames=camera['diagnostics']))
    else:
        camera,camera_record=store.run('camera_path',4,inputs,compute_camera)
    centers,extent=np.asarray(camera['centers']),np.asarray(camera['extent'])
    write_json(out/'render_stage.json',dict(camera_path=camera_record,encoding_status='pending'))
    from zoom_path import constrain_zoom
    subject_minimum=np.zeros(meta['frames'])
    for i in range(meta['frames']):
        if supported[i]:
            rotation=cv2.getRotationMatrix2D((0,0),float(roll[i]),1)[:,:2]
            points=(corners(boxes[i])-centers[i])@rotation.T
            subject_minimum[i]=max(2*np.abs(points[:,1]).max(),2*np.abs(points[:,0]).max()*c['output_height']/c['output_width'])/(1-2*c['margin_fraction'])
    _,minimum_extent,maximum_extent,zoom_conflicts=constrain_zoom(extent,centers,roll,
        (meta['width'],meta['height']),(c['output_width'],c['output_height']),subject_minimum,c.get('minimum_crop_short_side',180))
    edge_relaxed=extent>maximum_extent+1e-6
    for i in np.flatnonzero(zoom_conflicts):flags[i].append('zoom_constraints_conflict')
    for i in np.flatnonzero(edge_relaxed):flags[i].append('zoom_edge_coverage_relaxed')
    n,w,h,fps=meta['frames'],meta['width'],meta['height'],meta['fps']
    ow,oh=c['output_width'],c['output_height']
    tracks=[]
    selection_rows=None
    if c.get('tracking_mode') in ('dual','anchor') and c.get('tracking_render_path')=='selected':
        from tracking_selection import frame_provenance
        provenance={r['frame']:dict(r) for r in observations}
        corrections_path=out/'corrections.json'
        corrections=json.loads(corrections_path.read_text()) if corrections_path.exists() else {}
        for key,correction in corrections.items():
            if 'bbox' not in correction:continue
            i=int(key);box=correction['bbox']
            provenance[i]={'frame':i,'time':i/fps,'bbox':None if box is None else (np.array(box)/[w,h,w,h]*1000).tolist(),
                           'confidence':0 if box is None else 1,'visibility':'absent' if box is None else 'visible',
                           'manual':True,'selected_path':'manual' if box else 'neither','selection_reason':'Manual correction'}
        selection_rows=frame_provenance(list(provenance.values()),n,supported,confidence_threshold(c))
    for i in range(n):
        tracks.append({'frame':i,'time':i/fps,'bbox':boxes[i].tolist() if supported[i] else None,
            'roll':float(roll[i]),'center':centers[i].tolist(),'crop_height':float(extent[i]),'crop_width':float(extent[i]*ow/oh),
            'minimum_crop_short_side':c.get('minimum_crop_short_side',180),'render_size':[ow,oh],
            'zoom_seconds_per_doubling':planner['seconds_per_doubling'] if planner['enabled'] else c.get('zoom_seconds_per_doubling',.5),
            'zoom_smoothing_seconds':planner['zoom_seconds'] if planner['enabled'] else c.get('zoom_smoothing_seconds',.15),
            'zoom_edge_coverage_relaxed':bool(edge_relaxed[i]),
            'render_planner':planner if planner['enabled'] else None,
            'camera_diagnostics':camera.get('diagnostics',[None]*n)[i],
            'zoom':float(h/extent[i]),'flags':flags[i],
            'zoom_min':float(h/maximum_extent[i]) if maximum_extent[i]>0 else None,
            'zoom_max':float(h/minimum_extent[i]),'zoom_constraints_conflict':bool(zoom_conflicts[i]),
            **(selection_rows[i] if selection_rows else {}),
            **({k:v for k,v in level_rows[i].items() if k not in ('frame','time')} if level_rows else {})})
    from render_segments import Segments
    segments=Segments(c,meta,dict(camera=camera_record['key'],boxes=inputs['boxes'],supported=inputs['supported'],
        source=inputs.get('motion_key',meta['signature'])))
    cap=cv2.VideoCapture(c['video']);thumbs=out/'review_frames';thumbs.mkdir(exist_ok=True)
    def segment_frames(start,stop):
        if not cap.set(cv2.CAP_PROP_POS_FRAMES,start):raise RuntimeError(f'Cannot seek to render frame {start}')
        for i in range(start,stop):
            ok,frame=cap.read()
            if not ok:raise RuntimeError(f'Render decode failed at {i}')
            m=cv2.getRotationMatrix2D(tuple(centers[i]),float(roll[i]),float(oh/extent[i]))
            m[:,2]+=np.array([ow/2,oh/2])-centers[i]
            result=composite(frame,m,(ow,oh),c['feather_pixels'],boxes[i] if supported[i] else None)
            if i in meta['samples']:
                cv2.imwrite(str(thumbs/f'{i:07d}.jpg'),cv2.resize(frame,(960,540)))
                cv2.imwrite(str(thumbs/f'{i:07d}_out.jpg'),cv2.resize(result,(640,360)))
            yield frame,result
    try:
        for start in range(0,n,segments.length):
            stop=min(n,start+segments.length)
            if not segments.ready(start,stop):segments.encode(start,stop,segment_frames(start,stop))
            print(f'Render {stop}/{n}; {segments.reused} segments reused',flush=True)
    finally:cap.release()
    segments.assemble(ffmpeg_metadata_args(c['video']))
    preview=out/'focused.mp4'
    write_json(out/'tracks.json',tracks)
    write_sidecar(c)
    intervals=[]
    for i,f in enumerate(flags):
        reasons=sorted(f)
        if not reasons:
            continue
        if intervals and intervals[-1]['end_frame']==i-1 and intervals[-1]['reasons']==reasons:
            intervals[-1].update(end_frame=i,end=(i+1)/fps)
        else:
            intervals.append({'start_frame':i,'end_frame':i,'start':i/fps,'end':(i+1)/fps,'reasons':reasons})
    write_json(out/'review_flags.json',intervals)
    print(f'Created {preview}; {sum(bool(f) for f in flags)}/{n} frames have review flags.',flush=True)
    write_json(out/'render_stage.json',dict(camera_path=camera_record,encoding_status='complete',
        settings=dict(width=ow,height=oh,feather_pixels=c['feather_pixels']),
        outputs=['focused.mp4','comparison.mp4','tracks.json','review_flags.json']))


def make_comparison(c):
    """One encoded timeline guarantees that original and processed cannot drift apart."""
    out=Path(c['output_dir']);temp=out/'comparison.encoding.mp4'
    meta=json.loads((out/'meta.json').read_text())
    rate=str(meta['fps'])
    filters=(f'[0:v:0]setpts=PTS-STARTPTS,fps={rate},scale=960:540:force_original_aspect_ratio=decrease,'
             f'pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1[left];'
             f'[1:v:0]setpts=PTS-STARTPTS,fps={rate},scale=960:540:force_original_aspect_ratio=decrease,'
             f'pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1[right];'
             '[left][right]hstack=inputs=2:shortest=1[v]')
    subprocess.run([c['ffmpeg'],'-y','-hide_banner','-loglevel','error','-i',c['video'],
        '-i',str(out/'focused.mp4'),'-filter_complex',filters,'-map','[v]','-map','1:a?',
        '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','copy',
        *ffmpeg_metadata_args(c['video']),'-movflags','+faststart+use_metadata_tags',str(temp)],check=True)
    temp.replace(out/'comparison.mp4')
    print(f"Created synchronized comparison: {out/'comparison.mp4'}",flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('--stage', choices=['analyze', 'backward', 'level', 'level-render', 'render', 'compare', 'all'], default='all')
    parser.add_argument('--single', type=float)
    parser.add_argument('--analysis-fps',type=float,help='Qwen sample rate; independent of video playback FPS')
    parser.add_argument('--output-dir',help='Separate output directory for an FPS experiment')
    args = parser.parse_args()
    c = load_config(args.config)
    if args.analysis_fps is not None:set_analysis_fps(c,args.analysis_fps)
    if args.output_dir:
        c['output_dir']=str(Path(args.output_dir).resolve());Path(c['output_dir']).mkdir(parents=True,exist_ok=True)
    from effective_config import save as save_effective_config
    save_effective_config(c,args.stage)
    if args.stage in ('analyze', 'all'):
        analyze(c, args.single)
    if args.stage == 'backward':
        if c.get('tracking_mode') in ('dual','anchor'):
            raise ValueError('Dual tracking runs independent backward passes via --stage analyze; resume analyze to reuse cached forward requests')
        out=Path(c['output_dir']);first=out/'observations_first_pass.json'
        if not first.exists():
            previous=json.loads((out/'observations.json').read_text())
            if any(r.get('backward_attempt') for r in previous):
                raise RuntimeError('First-pass snapshot is missing; run --stage analyze before another backward pass')
            write_json(first,previous)
        meta=json.loads((out/'meta.json').read_text())
        set_analysis_fps(c,meta.get('analysis_fps',1/meta.get('sample_interval',.5)))
        model=api(c['api_url']+'/models')['data'][0]['id']
        results=run_backward(c,meta,json.loads(first.read_text()),model)
        write_json(out/'observations.json',results)
    if args.stage in ('level','level-render') or (args.stage=='all' and c.get('leveling_source')=='gyro'):
        from leveling import run_leveling
        run_leveling(c,api,args.single)
    if args.stage in ('render', 'level-render', 'all'):
        render(c)
    if args.stage == 'compare':
        make_comparison(c)


if __name__ == '__main__':
    main()
