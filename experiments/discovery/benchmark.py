"""Isolated discovery, blind crop observation, and identity comparison benchmark."""
import argparse, base64, json, statistics, sys, time, urllib.request
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import dual_tracking
from crop_description import describe_crop
from description_comparison import compare_descriptions
from model_response import completion
from tracking_response import validate_detection
from verification_policy import verification_decision


def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));tmp.replace(path)


def request(url,payload=None):
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=240) as response:return json.load(response)


def prepare(spec_path,out):
    spec=json.loads(spec_path.read_text());out.mkdir(parents=True,exist_ok=True)
    samples=[];crops=[]
    for clip in spec['clips']:
        config=json.loads(Path(clip['config']).read_text());labels=json.loads(Path(clip['corrections']).read_text())
        positives=sorted(int(k) for k,v in labels.items() if v.get('bbox'))
        negatives=sorted(int(k) for k,v in labels.items() if v.get('bbox') is None)
        ref=positives[len(positives)//2]
        candidates=[i for i in positives if abs(i-ref)>15]
        chosen=[candidates[i] for i in np.linspace(0,len(candidates)-1,3,dtype=int)] + negatives[:2]
        cap=cv2.VideoCapture(config['video']);fps=cap.get(cv2.CAP_PROP_FPS)
        def frame(i):
            cap.set(cv2.CAP_PROP_POS_FRAMES,i);ok,img=cap.read()
            if not ok:raise ValueError(f'Cannot decode {clip["name"]}:{i}')
            return img
        im=frame(ref);x1,y1,x2,y2=map(round,labels[str(ref)]['bbox'])
        reference=out/f'{clip["name"]}_reference.png';cv2.imwrite(str(reference),im[y1:y2,x1:x2])
        gyro=json.loads(Path(clip['gyro']).read_text()) if clip.get('gyro') else None
        for index in chosen:
            image=frame(index);h,w=image.shape[:2];stem=f'{clip["name"]}_{index}'
            path=out/f'{stem}.jpg';cv2.imwrite(str(path),image)
            box=labels[str(index)].get('bbox');target=config.get('approved_target_description') or config['target']
            sample=dict(id=stem,clip=clip['name'],frame=index,fps=fps,image=str(path.resolve()),width=w,height=h,
                bbox=box,reference=str(reference.resolve()),reference_frame=ref,target=target,
                roll=gyro['frames'][index]['roll'] if gyro else None,label_source=clip['corrections'])
            samples.append(sample)
            if box:
                x1,y1,x2,y2=map(round,box);crop=image[y1:y2,x1:x2]
            else:
                # Full absent frame is a deliberately difficult negative crop, never mislabeled as background-only.
                crop=image
            cp=out/f'{stem}_crop.png';cv2.imwrite(str(cp),crop)
            crops.append(dict(id=stem,image=str(cp.resolve()),target=target,expected=box is not None,kind='human_box' if box else 'human_absent_frame',sample=stem))
        cap.release()
    # Same visible crop, incompatible approved identity: hard color/category negatives.
    for crop in list(crops):
        if crop['expected']:
            opposite=next(s['target'] for s in samples if ('white' in s['clip']) != ('white' in crop['id']))
            crops.append(dict(crop,id=crop['id']+'_wrong_identity',target=opposite,expected=False,kind='cross_target_negative'))
    text=[]
    identity='A separate small sailboat seen from outside with a lime-green triangular sail. Exclude the camera boat and white-sailed boats. Partial or blurry views are acceptable.'
    cases=[
      ('A separate small boat carries a lime-green triangular sail.','external_view','isolated_subject','whole',True),
      ('A blurry small boat with a lime triangular sail, fine details unreadable.','external_view','isolated_subject','whole',True),
      ('Part of a lime-green triangular sail and a separate small hull; sail tip cut off.','external_view','isolated_subject','boundary_cut',True),
      ('A small white-sailed boat with a white hull.','external_view','isolated_subject','whole',False),
      ('Lime-green sail and white deck surround the camera with nearby rigging.','surrounding_camera','scene_dominated','boundary_cut',False),
      ('Open water and distant shoreline; no distinct object.','unclear','scene_dominated','unclear',False),
      ('A red car viewed from outside.','external_view','isolated_subject','whole',False),
      ('A separate lime-green sailing dinghy, partly occluded by foreground rigging.','external_view','isolated_subject','occluded',True),
    ]
    for i,(desc,view,comp,vis,expected) in enumerate(cases):
        text.append(dict(id=f'text_{i}',target=identity,description=dict(box_description=desc,viewpoint=view,composition=comp,visibility=vis),expected=expected))
    save(out/'manifest.json',dict(samples=samples,crops=crops,text=text,spec=spec))
    print(f'{len(samples)} held-out frames, {len(crops)} crop/identity pairs, {len(text)} fixed text cases')


def run(manifest,out,endpoint,model,tokens):
    assert model in [v['id'] for v in request(endpoint+'/models')['data']]
    data=json.loads(manifest.read_text());out.mkdir(parents=True,exist_ok=True);rows=[];calls=[]
    def api(url,payload):
        payload['chat_template_kwargs']={'enable_thinking':False}
        start=time.perf_counter()
        try:
            response=request(url,payload)
            calls.append(dict(seconds=time.perf_counter()-start,usage=response.get('usage'),finish_reason=response['choices'][0].get('finish_reason')))
            return response
        except Exception as e:
            calls.append(dict(seconds=time.perf_counter()-start,error=str(e)));raise
    def task(kind,identifier,fn,extra=None):
        calls.clear();start=time.perf_counter();row=dict(stage=kind,id=identifier,**(extra or {}))
        try:row['result']=fn()
        except Exception as e:row['error']=str(e)
        row.update(wall_seconds=time.perf_counter()-start,calls=list(calls));rows.append(row)
        save(out/'results.json',dict(model=model,rows=rows,manifest=str(manifest)))
        print(json.dumps({k:v for k,v in row.items() if k not in ('result','calls')}),flush=True)
        return row
    # No motion/history and no verification retries: isolate independent discovery.
    for sample in data['samples']:
        for path in (['raw_angle','leveled'] if sample['roll'] is not None else ['raw_angle']):
            def detect(s=sample,path=path):
                folder=out/s['id']/path;folder.mkdir(parents=True,exist_ok=True)
                import shutil
                shutil.copyfile(s['reference'],folder/'reference.jpg')
                image=cv2.imread(s['image']);captured={}
                def capture(completion,c,meta,index,direction,history,model,images,prompt,budget,validator):
                    captured.update(images=images,prompt=prompt,budget=budget)
                    return dict(raw='',bbox=None,confidence=0),{}
                old=dual_tracking.structured_tracking;dual_tracking.structured_tracking=capture
                try:
                    geometry=dual_tracking.observe_path(dict(target=s['target'],verify_boxes=False,box_verification_retries=0),
                        dict(cache=str(folder),fps=s['fps']),dict(frames={s['frame']:dict(roll=s['roll'] or 0)}),s['frame'],model,[],path,'forward',
                        (lambda *args:image,None,lambda *args:None))
                finally:dual_tracking.structured_tracking=old
                prompt=captured['prompt']
                if s['roll'] is None:prompt=prompt.replace('Current gyro-derived roll is 0.000000 degrees. Positive roll requires counterclockwise correction.','Gyro roll is unavailable. Do not infer a measured roll.')
                content=[]
                for image_path in captured['images']:
                    img=cv2.imread(str(image_path));h,w=img.shape[:2]
                    if max(h,w)>1280:img=cv2.resize(img,(round(w*1280/max(h,w)),round(h*1280/max(h,w))))
                    encoded=cv2.imencode('.jpg',img)[1]
                    content.append(dict(type='image_url',image_url=dict(url='data:image/jpeg;base64,'+base64.b64encode(encoded).decode())))
                content.append(dict(type='text',text=prompt))
                result=completion(api,endpoint+'/chat/completions',dict(model=model,messages=[dict(role='user',content=content)],temperature=0,max_tokens=650),folder/'request.json','discovery',validate_detection,cache=False)
                box=result.get('bbox');raw,polygon=dual_tracking.source_box(box,np.array(geometry['source_to_view']),geometry['view_size'],[s['width'],s['height']])
                pixel=(np.array(raw)*[s['width'],s['height'],s['width'],s['height']]/1000).tolist() if raw else None
                return dict(result,source_bbox=pixel,source_polygon=polygon,iou=dual_tracking.box_iou(pixel,s['bbox']) if s['bbox'] else None,
                    present=box is not None,view_size=geometry['view_size'],view_image=str(folder/f'{s["frame"]:07d}_{path}_view.jpg'))
            task('discovery',sample['id']+'_'+path,detect,dict(sample=sample['id'],path=path,expected=bool(sample['bbox'])))
    descriptions={}
    for crop in data['crops']:
        image=crop['image']
        if image not in descriptions:
            row=task('crop_description',crop['id'],lambda:describe_crop(image,model,endpoint,api,out/crop['id']/'describe.json'),dict(image=image))
            descriptions[image]=row.get('result')
        desc=descriptions[image]
        if desc:
            b={k:desc[k] for k in ('box_description','composition','visibility','viewpoint')}
            task('crop_verification',crop['id'],lambda:compare_descriptions(crop['target'],b,model,endpoint,api,out/crop['id']/'compare.json',cache=False),dict(expected=crop['expected'],kind=crop['kind'],image=image))
    for case in data['text']:
        task('text_comparison',case['id'],lambda:compare_descriptions(case['target'],case['description'],model,endpoint,api,out/case['id']/'compare.json',cache=False),dict(expected=case['expected']))
    summary={}
    for stage in sorted(set(r['stage'] for r in rows)):
        subset=[r for r in rows if r['stage']==stage];times=[r['wall_seconds'] for r in subset]
        metrics=dict(cases=len(subset),errors=sum('error' in r for r in subset),median_seconds=statistics.median(times),mean_seconds=statistics.mean(times),requests=sum(len(r['calls']) for r in subset))
        if stage=='discovery':
            for path in ('raw_angle','leveled'):
                group=[r for r in subset if r['path']==path]
                metrics[path]=dict(positive=sum(r['expected'] for r in group),localized_iou50=sum(r.get('result',{}).get('iou',0) is not None and (r.get('result',{}).get('iou') or 0)>=.5 for r in group),absent=sum(not r['expected'] for r in group),false_positive=sum(not r['expected'] and r.get('result',{}).get('present',False) for r in group))
        if stage in ('crop_verification','text_comparison'):
            def positive(r):
                a=r.get('result',{});return a.get('target_present',False) and a.get('match_score',0)>=.5 and a.get('exclusion_check')!='contradicted'
            metrics.update(correct=sum('result' in r and positive(r)==r['expected'] for r in subset),false_positive=sum(not r['expected'] and positive(r) for r in subset),false_negative=sum(r['expected'] and not positive(r) for r in subset))
        summary[stage]=metrics
    save(out/'summary.json',summary)

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--spec',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=sub.add_parser('run');a.add_argument('--manifest',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--endpoint',required=True);a.add_argument('--model',required=True);a.add_argument('--max-tokens',type=int,default=1000,help='Swap-runner compatibility; production stage budgets are used instead.')
    a=p.parse_args()
    if a.command=='prepare':prepare(a.spec,a.output)
    else:run(a.manifest,a.output,a.endpoint,a.model,a.max_tokens)
