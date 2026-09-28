"""Blind crop description matched against a trusted target description."""
import hashlib
import json
import math
from verification_policy import verification_decision, target_description
from pathlib import Path

import cv2
import numpy as np

from description_comparison import compare_descriptions, VERSION as COMPARISON_VERSION
from crop_description import describe_crop, VERSION as DESCRIPTION_VERSION

VERSION=7


def score(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('Verification score must be finite and between 0 and 1')
    return float(value)


def confidence_from_verification(model_confidence, description, comparison):
    # Proposal confidence and proposal notes are diagnostics only.
    value=score(comparison['match_score'])
    return value if comparison['target_present'] and comparison.get('exclusion_check')!='contradicted' else 0.


from lookout.events import timed as lookout_timed


@lookout_timed("verification")
def verify_box(c,view,box,box_note,model,reference,folder,api):
    """Crop in the exact image space Qwen measured (before any inverse rotation)."""
    height,width=view.shape[:2]
    pixels=np.array(box,dtype=float)*[width/1000,height/1000,width/1000,height/1000]
    x1,y1=np.maximum(0,np.floor(pixels[:2])).astype(int)
    x2,y2=np.minimum([width,height],np.ceil(pixels[2:])).astype(int)
    if x2<=x1 or y2<=y1:return {'error':'Empty crop','adjusted_confidence':0}
    crop=view[y1:y2,x1:x2]
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(crop.tobytes()+Path(reference).read_bytes()+json.dumps(
        [VERSION,DESCRIPTION_VERSION,COMPARISON_VERSION,model,target_description(c),c.get('approved_target_description'),box_note,box],sort_keys=True).encode()).hexdigest()[:24]
    output=folder/f'{key}.json'
    if output.exists():
        previous=json.loads(output.read_text())
        if not previous.get('error'):return dict(previous,cache_hit=True,identity_score=confidence_from_verification(None,previous.get('description'),previous['comparison']),decision=verification_decision(previous,c.get('tracking_selection',{}).get('confidence_threshold',.5)))
    crop_path=folder/f'{key}.png';cv2.imwrite(str(crop_path),crop)
    def save(data):
        temp=output.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,allow_nan=False));temp.replace(output)
    result={'version':VERSION,'crop_path':str(crop_path),'crop_pixels':[int(x1),int(y1),int(x2),int(y2)],
            'view_size':[width,height],'box_note':box_note}
    try:
        # Cache the trusted descriptor separately: it depends only on the reference,
        # target identity, model and verifier version, never the candidate crop.
        reference_key=hashlib.sha256(Path(reference).read_bytes()+json.dumps(
            [VERSION,DESCRIPTION_VERSION,COMPARISON_VERSION,model,target_description(c),c.get('approved_target_description')],sort_keys=True).encode()).hexdigest()[:24]
        reference_cache=folder/f'reference_{reference_key}.json'
        if c.get('approved_target_description'):
            trusted={'target_description':c['approved_target_description'],'source':'human_approved','input_revision':c.get('batch_input_revision')}
        elif reference_cache.exists():
            trusted=json.loads(reference_cache.read_text())
        else:
            observation=describe_crop(reference,model,c['api_url'],api,folder/f'{key}_reference_request.json')
            trusted=dict(observation,target_description=observation['box_description'],source='blind_reference_crop')
            temp=reference_cache.with_suffix('.tmp');temp.write_text(json.dumps(trusted,indent=2));temp.replace(reference_cache)
        result['reference_description']=trusted
        # Only the candidate image goes to this call: no target text, reference,
        # proposal, confidence, history or earlier messages.
        description=describe_crop(crop_path,model,c['api_url'],api,folder/f'{key}_describe_request.json')
        result['description']=description
        comparison=compare_descriptions(trusted['target_description'],{k:description[k] for k in ('box_description','composition','visibility','viewpoint')},model,c['api_url'],api,folder/f'{key}_compare_request.json')
        result['comparison']=comparison
        result['confidence_source']='blind_crop_text_match'
        result['identity_score']=confidence_from_verification(None,description,comparison)
    except Exception as error:
        result['error']=str(error)
        if hasattr(error,'details'):result['model_error']=error.details
    result['decision']=verification_decision(result,c.get('tracking_selection',{}).get('confidence_threshold',.5))
    save(result);return result
