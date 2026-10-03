"""Independent, coordinate-only visual leveling; no action-reframing imports."""
import base64,json,math,time,urllib.request
from pathlib import Path
import cv2
import numpy as np
try:
    from .core import save,load,digest
except ImportError:
    from core import save,load,digest

PROMPT='''Image 1 is a video frame. Image 2 shows numbered line candidates on that SAME frame.
Find a defensible distant reference for camera level. Prefer a true sea-sky horizon.
A distant land/water boundary is only an approximate shoreline reference: perspective
and terrain can slope. Distinguish it from a real horizon. Never use sails, masts,
rigging, foreground boat, wave crests, cloud edges, image borders, or ski slopes.
Select candidate_id only if that segment follows the visible reference. Otherwise
supply your own reference_line using actual visible endpoints, or return null if no
reference is defensible. Do not invent a horizontal line. Coordinates use 0..1000
relative to the entire image: top-left origin, y increases down, x2-x1 must be >=150.
Do not output an angle or direction; code computes them from the selected geometry.
Describe uncertainty briefly. confidence is certainty in the selected reference,
not a claim that shoreline perspective equals measured gravity. Return ONLY JSON:
{"candidate_id":integer or null,"reference_line":[x1,y1,x2,y2] or null,
"cue":"horizon|shoreline|vertical_geometry|unknown","confidence":0.0,
"note":"visible evidence and limitations in at most 40 words"}.
For vertical_geometry give the inferred horizontal reference, not a vertical segment.
If no defensible reference exists use candidate_id=null, reference_line=null,
cue="unknown", confidence=0. Never guess through foreground occlusion.'''

def request(url,payload=None,timeout=90):
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def candidates(image):
    h,w=image.shape[:2];edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),60,150)
    lines=cv2.HoughLinesP(edges,1,np.pi/720,70,minLineLength=w*.18,maxLineGap=25)
    if lines is None:return []
    result=[]
    for line in sorted(lines.reshape(-1,4),key=lambda p:-np.hypot(p[2]-p[0],p[3]-p[1])):
        x1,y1,x2,y2=map(float,line)
        if x2<x1:x1,y1,x2,y2=x2,y2,x1,y1
        if x2-x1<w*.35:continue
        slope=(y2-y1)/(x2-x1);angle=math.degrees(math.atan(slope));center=y1+slope*(w/2-x1)
        if any(abs(angle-p['angle'])<3 and abs(center-p['center'])<h*.035 for p in result):continue
        result.append(dict(line=[x1/w*1000,y1/h*1000,x2/w*1000,y2/h*1000],angle=angle,center=center))
        if len(result)>=12:break
    return result

def angle_from_line(line,width,height):
    if not isinstance(line,list) or len(line)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<=x<=1000 for x in line):raise ValueError('Invalid normalized reference line')
    x1,y1,x2,y2=line
    if x2-x1<150:raise ValueError('Reference span is too short')
    return math.degrees(math.atan2((y2-y1)*height,(x2-x1)*width))

def observe(job,sample,endpoint,model,stage='primary'):
    key=digest(dict(prompt=PROMPT,model=model,image_sha=sample['sha256'],version=1));path=job.out/stage/f'{sample["frame"]:09d}_{key[:16]}.json'
    old=load(path)
    if old:return old
    start=time.monotonic();row=dict(frame=sample['frame'],time=sample['time'],model=model,stage=stage,key=key,image=sample['image'],reference_line=None,angle=None,quality=0.)
    try:
        image=cv2.imread(str(job.out/sample['image']))
        if image is None:raise ValueError('Missing sample image')
        h,w=image.shape[:2];lines=candidates(image);marked=image.copy()
        for i,line in enumerate(lines):
            x1,y1,x2,y2=np.rint(np.array(line['line'])*[w/1000,h/1000,w/1000,h/1000]).astype(int)
            cv2.line(marked,(x1,y1),(x2,y2),(255,80,200),2);x=max(5,min(w-35,(x1+x2)//2));y=max(22,min(h-8,(y1+y2)//2))
            cv2.putText(marked,str(i),(x,y),0,.7,(0,0,0),4);cv2.putText(marked,str(i),(x,y),0,.7,(255,255,255),1)
        content=[]
        for im in (image,marked):
            encoded=cv2.imencode('.jpg',im,[cv2.IMWRITE_JPEG_QUALITY,92])[1]
            content.append(dict(type='image_url',image_url=dict(url='data:image/jpeg;base64,'+base64.b64encode(encoded).decode())))
        content.append(dict(type='text',text=PROMPT))
        payload=dict(model=model,messages=[dict(role='user',content=content)],temperature=0,max_tokens=500,chat_template_kwargs=dict(enable_thinking=False),response_format=dict(type='json_object'))
        answer=request(endpoint.rstrip('/')+'/chat/completions',payload,timeout=min(job.config['request_timeout'],max(1,job.remaining())))
        row.update(response=answer,candidates=lines,prompt_version=digest(PROMPT))
        choice=answer['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('Model output truncated')
        raw=choice['message']['content'];value=json.loads(raw[raw.index('{'):raw.rindex('}')+1]);cid=value.get('candidate_id')
        if cid is not None and (type(cid) is not int or not 0<=cid<len(lines)):raise ValueError('Invalid candidate ID')
        line=lines[cid]['line'] if cid is not None else value.get('reference_line');score=value.get('confidence',0)
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid visual confidence')
        cue=value.get('cue','unknown')
        if cue not in ('horizon','shoreline','vertical_geometry','unknown'):raise ValueError('Invalid visual cue')
        angle=angle_from_line(line,w,h) if line is not None else None
        quality=(min(score,.6) if cue=='shoreline' else score) if angle is not None and cue!='unknown' else 0.
        row.update(reference_line=line,angle=angle,quality=quality,cue=cue,note=value.get('note',''),candidate_id=cid,model_confidence=score)
    except Exception as e:row['error']=f'{type(e).__name__}: {e}'
    row['seconds']=time.monotonic()-start;save(path,row);job.charge(stage,row['seconds']);return row

def observations(job,stage):
    rows=[]
    folder=job.out/stage
    if not folder.exists():return rows
    for path in folder.glob('*.json'):
        row=load(path)
        if row and row.get('prompt_version') in (None,digest(PROMPT)):rows.append(row)
    # This job locks effective models in its planning manifest; cache files include model hash.
    return sorted(rows,key=lambda r:r['frame'])
