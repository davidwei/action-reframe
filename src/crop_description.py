"""Identical blind image-to-text observation for reference and candidate crops."""
import base64
import json
from pathlib import Path
import cv2
from model_response import completion

VERSION=2
PROMPT='''Describe only what is visibly present in this image crop.
Focus on the prominent foreground object or objects: object type, shape, colors,
markings, equipment, and visible parts. Describe the object itself, not the scene.
Omit background scenery and incidental surroundings such as sky, terrain, water,
buildings or distant vegetation when they are merely behind or around an object.
Do not treat common background areas as object identity features.
If multiple objects are visible, distinguish their features; do not merge them into
one imaginary object or infer which one a user intends to follow.
If the image contains only background with no distinct object, explicitly say so
and identify that background briefly. Do not invent an object to satisfy the prompt.
Describe supported coarse shapes and colors even when blurred. Blur is image
quality, not proof that an object is absent. Briefly mention ambiguity, unreadable
details and object parts cut off at the edges, separately from visible identity.
Do not guess what lies outside the crop or infer an intended subject.
Use at most 120 words in 2–4 short sentences. State each feature only once; prioritize
identity features and visible limitations. Stop after those sentences.
Return ONLY JSON: {"box_description":"concise object-focused visible contents and limitations"}.
'''


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
