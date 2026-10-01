"""Ablation: select level reference visually, derive direction only from coordinates.

Production code is unchanged. The adapter removes direction from the model's output
schema, retains the untouched response for audit, and supplies a deterministic value
to the existing result parser. Existing cue/confidence/geometry checks remain active.
"""
import argparse,copy,hashlib,json,statistics,time
from pathlib import Path
import cv2
from benchmark import request
from leveling import visual_observation,visual_candidates,line_angle

DIRECTION_FIELD='"direction":"rises_right" or "falls_right" or "horizontal" or "unknown",'


def direction(angle):
    if angle is None:return 'unknown'
    return 'falls_right' if angle>2 else 'rises_right' if angle < -2 else 'horizontal'


def run(manifest_path,out,endpoint,model,tokens):
    assert model in [v['id'] for v in request(endpoint+'/models')['data']]
    manifest=json.loads(manifest_path.read_text());rows=[];out.mkdir(parents=True,exist_ok=True)
    for repeat in range(manifest.get('repeats',2)):
        for sample in manifest['samples']:
            folder=out/f"{sample['id']}_repeat{repeat}";folder.mkdir(exist_ok=True)
            image=cv2.imread(sample['image']);h,w=image.shape[:2]
            if w>1280:image=cv2.resize(image,(1280,round(h*1280/w)))
            candidates=visual_candidates(image);calls=[]
            def api(url,payload):
                payload['max_tokens']=tokens;payload['chat_template_kwargs']={'enable_thinking':False}
                parts=payload['messages'][0]['content'];prompt=parts[-1]['text']
                assert DIRECTION_FIELD in prompt
                parts[-1]['text']=prompt.replace(DIRECTION_FIELD,'')+'\nDo not output a rotation direction or angle. Code calculates both from the selected line endpoints.'
                (folder/'prompt.txt').write_text(parts[-1]['text'])
                start=time.perf_counter();answer=request(url,payload)
                calls.append(dict(seconds=time.perf_counter()-start,usage=answer.get('usage'),finish_reason=answer['choices'][0].get('finish_reason'),response=answer['choices'][0]['message']))
                (folder/'raw_response.json').write_text(json.dumps(answer,indent=2))
                if answer['choices'][0].get('finish_reason')=='length':raise ValueError('Truncated model output')
                raw=answer['choices'][0]['message']['content'];value=json.loads(raw[raw.index('{'):raw.rindex('}')+1])
                cid=value.get('candidate_id')
                if cid is not None and (type(cid) is not int or not 0<=cid<len(candidates)):raise ValueError('Invalid candidate ID')
                line=candidates[cid]['line'] if cid is not None else value.get('reference_line')
                angle=line_angle(line,sample['width'],sample['height']) if line is not None else None
                value['direction']=direction(angle)
                adapted=copy.deepcopy(answer);adapted['choices'][0]['message']['content']=json.dumps(value)
                return adapted
            meta=dict(cache=str(Path(sample['image']).parent),width=sample['width'],height=sample['height'],fps=1,signature=hashlib.sha256(Path(sample['image']).read_bytes()).hexdigest())
            start=time.perf_counter();result=visual_observation(dict(output_dir=str(folder),api_url=endpoint),meta,sample['id'],model,api)
            result['direction_source']='computed_from_selected_line'
            row=dict(sample=sample,repeat=repeat,result=result,calls=calls,wall_seconds=time.perf_counter()-start,cached=not bool(calls))
            if result.get('roll') is not None and sample.get('gyro_roll') is not None:row['gyro_absolute_difference_degrees']=abs(result['roll']-sample['gyro_roll'])
            rows.append(row)
            (out/'results.json').write_text(json.dumps(dict(model=model,rows=rows,max_tokens=tokens,manifest=str(manifest_path)),indent=2))
            print(json.dumps(dict(id=sample['id'],repeat=repeat,seconds=row['wall_seconds'],roll=result.get('roll'),confidence=result.get('orientation_confidence'),error=result.get('error'))),flush=True)
    original=[r for r in rows if r['sample'].get('rotation_degrees',0)==0]
    times=[r['calls'][0]['seconds'] for r in original if r['calls']]
    summary=dict(model=model,requests=sum(len(r['calls']) for r in rows),original_median_seconds=statistics.median(times),errors=sum(bool(r['result'].get('error')) for r in rows),usable=sum(r['result'].get('orientation_confidence',0)>0 for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--endpoint',required=True);p.add_argument('--model',required=True);p.add_argument('--max-tokens',type=int,default=400);a=p.parse_args();run(a.manifest,a.output,a.endpoint,a.model,a.max_tokens)
