"""Use reliable motion for framing without promoting it to verified identity."""
import math
from optical_diagnostics import load
from verification_policy import accepted_row


def motion_usable(row):
    box=row.get('bbox') if row else None
    return bool(row and row.get('motion_reliable') and not row.get('manual') and not row.get('scene_cut')
        and isinstance(box,(list,tuple)) and len(box)==4
        and all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1000 for v in box)
        and box[2]>box[0] and box[3]>box[1])


def propagation_usable(row,threshold):
    return accepted_row(row,threshold) or motion_usable(row)


def merge_motion(observations,meta,folder,threshold):
    rows={r['frame']:dict(r) for r in observations}
    predictions={}
    # Historical checkpoints have measurements too; do not fabricate intermediate frames.
    for row in observations:
        proposals=list(row.get('propagation_validation',{}).values())
        if row.get('analysis_source')=='flow_crop_validation':proposals.append(row)
        for proposal in proposals:
            if proposal.get('bbox') is not None and proposal.get('analysis_source')=='flow_crop_validation':
                predictions[str(row['frame'])]=dict(frame=row['frame'],reliable=True,
                    bbox_px=[v*(meta['height'] if i%2 else meta['width'])/1000 for i,v in enumerate(proposal['bbox'])],
                    motion_quality=proposal.get('motion_quality'))
                break
    predictions.update(load(folder))
    for key,p in predictions.items():
        i=int(key);previous=rows.get(i,{})
        if not 0<=i<meta['frames'] or previous.get('manual') or previous.get('scene_cut') or accepted_row(previous,threshold):continue
        if not p.get('reliable') or not p.get('bbox_px'):continue
        box=[v/(meta['height'] if j%2 else meta['width'])*1000 for j,v in enumerate(p['bbox_px'])]
        motion=dict(previous,frame=i,time=i/meta['fps'],bbox=box,confidence=0,visibility='visible',
            analysis_source='optical_unverified',selected_path='optical_unverified',localized=False,
            motion_reliable=True,motion_quality=p.get('motion_quality'),identity_verified=False,
            selection_flags=['optical_identity_unverified'],selection_reason='Reliable optical motion used for framing; identity is unverified')
        if motion_usable(motion):rows[i]=motion
    return [rows[i] for i in sorted(rows)]
