"""Validated, audited tracking completions retaining multimodal history and retry budgets."""
import math
from pathlib import Path
from model_response import completion

ABSENCE_HINT = 'bbox must be null for absence or uncertainty, never [null] or an empty array. Otherwise return exactly four finite numbers [xmin,ymin,xmax,ymax]. Keep note and box_note to one short sentence each.'


def validate_detection(result):
    if 'bbox' not in result:raise ValueError('Missing bbox; use null for absence')
    box=result['bbox']
    if box is not None and (not isinstance(box,list) or len(box)!=4 or
        not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1000 for v in box) or
        box[0]>=box[2] or box[1]>=box[3]):raise ValueError('Invalid Qwen rectangle; absent bbox must be null, never [null]')
    score=result.get('confidence')
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid confidence')
    if result.get('visibility') not in ('visible','partial','absent','uncertain'):raise ValueError('Invalid visibility')


def structured_tracking(contextual,c,meta,index,direction,history,model,images,prompt,tokens,validator,stage='tracking detection'):
    folder=Path(meta['cache'])/'structured_response';folder.mkdir(parents=True,exist_ok=True)
    audits=[]
    def request(_url,payload):
        texts=payload['messages'][0]['content']
        task='\n'.join(part['text'] for part in texts)
        response,audit=contextual(dict(c,_structured_tracking=True,_stage_validator=validator),dict(meta,cache=str(folder/str(len(audits)))),
            index,direction,history,model,images,task,payload['max_tokens'])
        audits.append(audit)
        return response
    payload=dict(model=model,max_tokens=tokens,messages=[dict(role='user',content=[dict(type='text',text=prompt)])])
    result=completion(request,'contextual',payload,folder/'request.json',stage,validator,retry_invalid=True,correction_hint=ABSENCE_HINT if stage=='tracking detection' else '')
    audit=dict(audits[-1],structured_response_attempts=len(audits),response_file=result['response_file'])
    return result,audit
