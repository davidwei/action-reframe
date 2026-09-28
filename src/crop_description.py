"""Identical blind image-to-text observation for reference and candidate crops."""
import base64
import json
from pathlib import Path
import cv2
from model_response import completion

VERSION=1
PROMPT='''Describe only what is visibly present in this image crop.
List visible objects, colors, shapes, markings, equipment, parts and background. Mention blur, ambiguity and objects cut off at the edges.
Describe coarse visible shapes and colors even if blurred. Blur is image quality, not proof that an object is absent; separate visible content from unreadable details.
Do not guess what lies outside the crop or infer an intended subject. If it contains only background, say so.
Return ONLY JSON: {"box_description":"literal visible contents and limitations"}.'''


def describe_crop(path, model, api_url, api, audit):
    """One image, one fixed prompt. No target, roles, notes, or history as inputs."""
    image=cv2.imread(str(path))
    if image is None or not image.size:raise ValueError('Cannot read crop for description')
    h,w=image.shape[:2];scale=min(1,960/max(h,w))
    if scale<1:image=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))))
    ok,encoded=cv2.imencode('.png',image)
    if not ok:raise ValueError('Cannot encode description crop')
    content=[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(encoded).decode()}},
             {'type':'text','text':PROMPT}]
    request={'model':model,'messages':[{'role':'user','content':content}],'temperature':0,'max_tokens':1000}
    audit=Path(audit);audit.parent.mkdir(parents=True,exist_ok=True)
    audit.write_text(json.dumps({'description_version':VERSION,'model':model,'prompt':PROMPT,'images':[str(path)],'temperature':0,'max_tokens':1000},indent=2))
    def validate(result):
        if not isinstance(result.get('box_description'),str) or not result['box_description'].strip():raise ValueError('Missing crop description')
    result=completion(api,api_url+'/chat/completions',request,audit,'crop description',validate)
    result['description_version']=VERSION
    audit.with_name(audit.stem+'_response.json').write_text(json.dumps(result,indent=2))
    return result
