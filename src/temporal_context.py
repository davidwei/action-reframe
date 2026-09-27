"""Directional frame history with auditable, bounded visual/text context for Qwen."""
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

CONTEXT_VERSION = 3


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


def select_history(records, settings):
    """Last in traversal order, not largest timestamp (also works backward)."""
    recent_count=int(settings.get('recent_images',5))
    moderate_count=int(settings.get('moderate_images',5))
    high_count=int(settings.get('high_images',5))
    low=float(settings.get('moderate_confidence',.65))
    high=float(settings.get('high_confidence',.85))
    if not 3<=recent_count<=5 or not 0<=moderate_count<=5 or not 0<=high_count<=5 or not 0<=low<high<=1:
        raise ValueError('History needs 3–5 recent frames, confidence quotas of 0–5, and 0 <= moderate < high <= 1')
    def reliable(r):
        score=r.get('confidence')
        return (r.get('bbox') is not None and r.get('visibility') in ('visible','partial')
                and not r.get('error') and isinstance(score,(int,float)) and math.isfinite(score))
    recent=records[-recent_count:]
    chosen={r['frame'] for r in recent}
    moderate_added=[];high_added=[]
    def count_above(threshold):
        return sum(r['frame'] in chosen and reliable(r) and threshold<=r['confidence']<=1 for r in records)
    count=count_above(low)
    for r in reversed(records[:-recent_count]):
        if count>=moderate_count:break
        if reliable(r) and low<=r['confidence']<=1:
            chosen.add(r['frame']);moderate_added.append(r['frame']);count+=1
    count=count_above(high)
    for r in reversed(records[:-recent_count]):
        if count>=high_count:break
        if r['frame'] not in chosen and reliable(r) and high<=r['confidence']<=1:
            chosen.add(r['frame']);high_added.append(r['frame']);count+=1
    groups={'recent':[r['frame'] for r in recent],
            'moderate_or_high_added':moderate_added,'high_added':high_added}
    return [r for r in records if r['frame'] in chosen],groups



def build_context(history,meta,current_frame,direction,settings,frame_loader,compression=0):
    records=directional_records(history,meta,current_frame,direction)
    references=list(dict.fromkeys(meta.get('user_reference_frames',[])))
    key=context_key(history,meta,current_frame,direction,dict(settings,user_reference_frames=references))
    folder=Path(meta['cache'])/'context'/key;folder.mkdir(parents=True,exist_ok=True)
    (folder/'history.json').write_text(json.dumps(records,indent=2,allow_nan=False))
    selected,groups=select_history(records,settings)
    # Keep membership fixed when a request is large; reduce image resolution instead.
    compact=[dict(r,note=r['note'][:240],level_note=(r.get('level_note') or '')[:180]) for r in selected]
    if settings.get('omit_box_coordinates'):
        compact=[{k:v for k,v in r.items() if k not in ('bbox','note')} for r in compact]
    text=('TEMPORAL HISTORY — '+direction.upper()+' traversal. '
          'These are prior hypotheses, NOT ground truth. Verify identity and motion against the CURRENT image. '
          'Start with recent frames, then top up moderate-or-high and high confidence quotas from nearest older frames; only selected records are sent; all history remains on disk. '
          'All historical boxes and images use ORIGINAL RAW FULL frames with boxes normalized 0–1000. '
          'Records are ordered in traversal direction, most recently visited last. '
          'User-selected reference frames can be from any time and are identity references, NOT preceding motion evidence. '
          'Moderate and high confidence are model reports, not guarantees. Image group membership can overlap; images are deduplicated.\n'+
          json.dumps({'image_groups':groups,'user_reference_frames':references,'individual_frame_records':compact},separators=(',',':'),allow_nan=False))
    if settings.get('omit_box_coordinates'):
        text=text.replace('All historical boxes and images use ORIGINAL RAW FULL frames with boxes normalized 0–1000.', 'Historical full-frame images use ORIGINAL RAW views. Previous box coordinates are withheld.')
    order=list(dict.fromkeys(references+[r['frame'] for r in selected]))
    images=[];width=max(224,768//(2**compression))
    for index in order:
        labels=(['USER-SELECTED IDENTITY REFERENCE'] if index in references else [])
        labels += [name for name,indices in groups.items() if index in indices]
        label=f"{' / '.join(labels)} | RAW frame {index} | {index/meta['fps']:.3f}s"
        path=folder/f'c{compression}_selected_{index:07d}.jpg'
        if not path.exists():
            im=frame_loader(index);h,w=im.shape[:2]
            im=cv2.resize(im,(width,max(1,round(h*width/w))))
            cv2.imwrite(str(path),im,[cv2.IMWRITE_JPEG_QUALITY,90])
        images.append({'path':str(path),'label':label,'frames':[index]})
    # Add exact identity crops only for human labels admitted by the existing frame quotas.
    manual_crops=[]
    for record in selected:
        if record['source']!='manual' or record.get('bbox') is None:continue
        index=record['frame'];im=frame_loader(index);h,w=im.shape[:2]
        original_record=next(r for r in reversed(history) if r['frame']==index)
        box=np.asarray(original_record['bbox'])*[w/1000,h/1000,w/1000,h/1000]
        x1,y1=np.maximum(0,np.floor(box[:2])).astype(int)
        x2,y2=np.minimum([w,h],np.ceil(box[2:])).astype(int)
        if x2<=x1 or y2<=y1:continue
        path=folder/f'human_target_{index:07d}.png'
        cv2.imwrite(str(path),im[y1:y2,x1:x2])
        entry={'path':str(path),'label':f'HUMAN-CONFIRMED TARGET CROP | frame {index} | {index/meta["fps"]:.3f}s | identity only, not current location','frames':[index],'kind':'human_target_crop'}
        images.append(entry);manual_crops.append(index)
    selected_ids=set(order)
    audit={'version':CONTEXT_VERSION,'direction':direction,'history_key':key,'history_count':len(records),
           'individual_record_count':len(compact),'summarized_record_count':0,
           'omitted_record_count':len(records)-len(compact),
           'visual_frame_count':len(order),'unsent_visual_frame_count':sum(r['frame'] not in selected_ids for r in records),
           'recent_image_frames':groups['recent'],'image_groups':groups,'user_reference_frames':references,
           'manual_crop_frames':manual_crops,'attached_image_count':len(images),
           'selected_image_frames':order,'compression':compression,'image_width':width,
           'history_file':str(folder/'history.json'),'images':images}
    return text,images,audit,folder
