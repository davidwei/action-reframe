"""Directional frame history with auditable, bounded visual/text context for Qwen."""
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

CONTEXT_VERSION = 1


def frame_record(r, meta):
    shore=r.get('shoreline');angle=r.get('manual_roll')
    if angle is None and shore is not None and len(shore)==4 and shore[2]!=shore[0]:
        angle=math.degrees(math.atan((shore[3]-shore[1])*meta['height']/((shore[2]-shore[0])*meta['width'])))
    return {'frame':r['frame'],'time':round(r.get('time',r['frame']/meta['fps']),3),
        'bbox':None if r.get('bbox') is None else [round(v,2) for v in r['bbox']],
        'confidence':r.get('confidence'),'visibility':r.get('visibility'),
        'shoreline':shore,'roll_degrees':None if angle is None else round(angle,3),
        'level_confidence':r.get('level_confidence'),'level_note':r.get('level_note'),
        'source':r.get('analysis_source','manual' if r.get('manual') else 'forward'),
        'scene_cut':r.get('scene_cut',False),'error':r.get('error'),
        'note':r.get('note','')}


def directional_records(history, meta, current_frame, direction):
    if direction not in ('forward','backward'):raise ValueError('Unknown context direction')
    by_frame={r['frame']:r for r in history if
              (r['frame']<current_frame if direction=='forward' else r['frame']>current_frame)}
    return [frame_record(by_frame[i],meta) for i in sorted(by_frame,reverse=direction=='backward')]


def context_key(history,meta,current_frame,direction,settings):
    records=directional_records(history,meta,current_frame,direction)
    return hashlib.sha256(json.dumps([CONTEXT_VERSION,direction,records,settings],sort_keys=True).encode()).hexdigest()[:24]


def summarize(records):
    if not records:return None
    angles=[r['roll_degrees'] for r in records if r['roll_degrees'] is not None]
    scores=[r['confidence'] for r in records if isinstance(r['confidence'],(int,float))]
    visible=[r for r in records if r['bbox'] is not None and (r['confidence'] or 0)>=.65]
    return {'record_count':len(records),'first_frame':records[0]['frame'],'last_frame':records[-1]['frame'],
            'time_range':[min(r['time'] for r in records),max(r['time'] for r in records)],
            'confident_object_count':len(visible),'confidence_range':[min(scores),max(scores)] if scores else None,
            'roll_range_degrees':[min(angles),max(angles)] if angles else None,
            'scene_cut_frames':[r['frame'] for r in records if r['scene_cut']],
            'last_record':records[-1]}


def build_context(history,meta,current_frame,direction,settings,frame_loader,compression=0):
    records=directional_records(history,meta,current_frame,direction)
    key=context_key(history,meta,current_frame,direction,settings)
    folder=Path(meta['cache'])/'context'/key;folder.mkdir(parents=True,exist_ok=True)
    # The full record list is retained, even if the request needs bounded summaries.
    (folder/'history.json').write_text(json.dumps(records,indent=2,allow_nan=False))
    compact=[dict(r,note=r['note'][:240],level_note=(r.get('level_note') or '')[:180]) for r in records]
    limit=max(1500,int(settings.get('history_char_budget',64000))/(2**compression))
    split=0
    while split<len(compact)-1 and len(json.dumps(compact[split:],separators=(',',':')))>limit:
        split+=max(1,(len(compact)-split)//8)
    old=compact[:split]
    groups=[]
    if old:
        size=max(1,math.ceil(len(old)/8))
        groups=[summarize(old[i:i+size]) for i in range(0,len(old),size)]
    table={'older_history_summaries':groups,'individual_frame_records':compact[split:]}
    text=('TEMPORAL HISTORY — '+direction.upper()+' traversal. '
          'These are prior hypotheses, NOT ground truth. They include failures and low-confidence estimates. '
          'Use previous object locations, visibility, confidence, shoreline endpoints and signed roll to assess changes. '
          'Verify against the CURRENT image; do not repeat a bad estimate or assume the target remains visible. '
          'A positive roll means the source shoreline descends toward the right; negative means it rises. '
          'All recorded boxes/shorelines are normalized 0–1000 in their ORIGINAL FULL frames. '
          'Frame records are ordered in traversal direction, with the most recently visited/nearest frame last. '
          'History images below are explicitly timestamped and must not be mistaken for the current frame.\n'+
          json.dumps(table,separators=(',',':'),allow_nan=False))
    recent_count=min(len(records),max(1,int(settings.get('recent_images',3))-compression))
    recent=records[-recent_count:] if recent_count else []
    older=records[:-recent_count] if recent_count else records
    capacity=max(0,int(settings.get('history_visual_frames',128))//(2**compression))
    if len(older)>capacity:
        selected=[older[i] for i in np.linspace(0,len(older)-1,capacity,dtype=int)] if capacity else []
    else:selected=older
    images=[]
    for offset in range(0,len(selected),16):
        group=selected[offset:offset+16]
        path=folder/f'c{compression}_history_{offset//16:03d}.jpg'
        if not path.exists():
            canvas=np.zeros((4*154,4*224,3),np.uint8)
            for k,r in enumerate(group):
                im=frame_loader(r['frame']);thumb=cv2.resize(im,(224,126))
                x,y=(k%4)*224,(k//4)*154
                canvas[y+28:y+154,x:x+224]=thumb
                cv2.putText(canvas,f"f{r['frame']} {r['time']:.3f}s",(x+4,y+20),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
            cv2.imwrite(str(path),canvas,[cv2.IMWRITE_JPEG_QUALITY,88])
        images.append({'path':str(path),'label':'Older history contact sheet, ordered left-to-right then top-to-bottom',
                       'frames':[r['frame'] for r in group]})
    for r in recent:
        path=folder/f"recent_{r['frame']:07d}.jpg"
        if not path.exists():
            im=frame_loader(r['frame']);h,w=im.shape[:2];im=cv2.resize(im,(768,round(h*768/w)))
            im=cv2.copyMakeBorder(im,30,0,0,0,cv2.BORDER_CONSTANT)
            cv2.putText(im,f"HISTORY frame {r['frame']} | {r['time']:.3f}s",(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
            cv2.imwrite(str(path),im,[cv2.IMWRITE_JPEG_QUALITY,90])
        images.append({'path':str(path),'label':f"Recent HISTORY frame {r['frame']} at {r['time']:.3f}s",'frames':[r['frame']]})
    audit={'version':CONTEXT_VERSION,'direction':direction,'history_key':key,'history_count':len(records),
           'individual_record_count':len(compact)-split,'summarized_record_count':split,
           'visual_frame_count':len(selected)+len(recent),'unsent_visual_frame_count':len(older)-len(selected),
           'recent_image_frames':[r['frame'] for r in recent], 'compression':compression,
           'history_file':str(folder/'history.json'),'images':images}
    return text,images,audit,folder
