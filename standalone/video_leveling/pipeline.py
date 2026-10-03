"""Resumable sampling, model passes, background motion and annotation export."""
import hashlib,json,math,os,time
from pathlib import Path
import cv2
import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve
try:
    from .core import save,load,digest,decode,read_samples
    from .visual import observe,observations,request
    from .motion import rotation
except ImportError:
    from core import save,load,digest,decode,read_samples
    from visual import observe,observations,request
    from motion import rotation

SHARES=dict(prepare=.10,primary=.40,motion=.30,refine=.075,review=.075,export=.05)

def allowance(job,stage):
    reserve=min(120,job.config['budget_seconds']*.025) if stage!='export' else 0
    return max(0,min(job.config['budget_seconds']*SHARES[stage]-job.spent(stage),job.remaining()-reserve))

def write_npz(path,**arrays):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as f:np.savez_compressed(f,**arrays);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def valid_chunk(path,marker):
    m=load(marker)
    if not m or not Path(path).exists():return None
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=m['sha256']:return None
    return m

def thumbnail(job,frame,image):
    h,w=image.shape[:2]
    if w>1280:image=cv2.resize(image,(1280,round(h*1280/w)))
    encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,92])[1].tobytes()
    p=job.out/'images'/f'{frame:09d}.jpg';p.parent.mkdir(exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_bytes(encoded);os.replace(tmp,p)
    return dict(frame=frame,time=frame/job.meta['fps'],image=str(p.relative_to(job.out)),sha256=hashlib.sha256(encoded).hexdigest())

def prepare(job):
    fps=min(job.config['base_fps'],max(.01,job.config['budget_seconds']*.45/job.config['primary_seconds']/job.meta['duration_seconds']))
    plan=load(job.out/'sampling.json')
    if not plan:plan=dict(fps=fps,time_basis='video playback seconds',prompt='visual-v1');save(job.out/'sampling.json',plan)
    wanted=set(np.rint(np.arange(0,job.meta['duration_seconds'],1/plan['fps'])*job.meta['fps']).astype(int));wanted.add(job.meta['frames']-1)
    completed=0
    for start,end in job.intervals():
        marker=job.out/'samples'/f'{start:09d}.json';data=job.out/'samples'/f'{start:09d}.npz'
        m=valid_chunk(data,marker)
        if m and all((job.out/s['image']).exists() and hashlib.sha256((job.out/s['image']).read_bytes()).hexdigest()==s['sha256'] for s in m['samples']):completed+=1;continue
        if allowance(job,'prepare')<=0:break
        with job.timed('prepare'):
            seen=np.zeros(end-start,bool);samples=[]
            for index,t,frame in decode(job,start,end):
                seen[index-start]=True
                if index in wanted:samples.append(thumbnail(job,index,frame.to_ndarray(format='bgr24')))
            sha=write_npz(data,valid=np.packbits(seen),start=np.array(start),end=np.array(end))
            save(marker,dict(start=start,end=end,samples=samples,sha256=sha,decoded=int(seen.sum()),missing=int((~seen).sum())))
        completed+=1;job.status('prepare','running',completed_chunks=completed,total_chunks=len(job.intervals()))
    job.status('prepare','complete' if completed==len(job.intervals()) else 'budget_limited',completed_chunks=completed,total_chunks=len(job.intervals()))


def check_model(endpoint,model):
    if model not in [x['id'] for x in request(endpoint.rstrip('/')+'/models')['data']]:raise ValueError(f'Expected served model {model}')

def visual_pass(job,endpoint,model):
    check_model(endpoint,model);samples=read_samples(job)
    if not samples:raise ValueError('No decoded samples available')
    # Stratify rather than exhaust the budget on only the beginning of a long video.
    cap=max(1,int((job.config['budget_seconds']*SHARES['primary'])/job.config['primary_seconds']))
    chosen=[samples[i] for i in np.unique(np.linspace(0,len(samples)-1,min(cap,len(samples)),dtype=int))]
    examined=0
    for n,s in enumerate(chosen):
        if allowance(job,'primary')<1:break
        observe(job,s,endpoint,model,'primary')
        examined=n+1
        if n%10==0:job.status('primary','running',examined=n+1,planned=len(chosen),model=model)
    job.status('primary','complete' if examined==len(chosen) else 'budget_limited',examined=len(observations(job,'primary')),planned=len(chosen),model=model)


def chosen_observations(job):
    primary={r['frame']:r for r in observations(job,'primary')+observations(job,'refine')}
    for r in observations(job,'review'):
        old=primary.get(r['frame']);r=dict(r)
        if old and old.get('angle') is not None and r.get('angle') is not None:
            disagreement=abs((r['angle']-old['angle']+90)%180-90);r['model_disagreement_degrees']=disagreement
            if disagreement>5:r['quality']=min(r['quality'],.3);r['needs_review']=True
        if r.get('angle') is not None and r.get('quality',0)>0:primary[r['frame']]=r
    return sorted(primary.values(),key=lambda r:r['frame'])


def motion_pass(job):
    anchors=[r for r in chosen_observations(job) if r.get('angle') is not None and r.get('quality',0)>=.3]
    signature=digest(dict(anchors=[(r['frame'],r['key'],r.get('reference_line')) for r in anchors],width=job.config['motion_width'],fps=job.config['motion_fps'],version=1))[:20]
    folder=job.out/'motion'/signature;folder.mkdir(parents=True,exist_ok=True)
    save(job.out/'motion.json',dict(signature=signature,folder=str(folder.relative_to(job.out))))
    fps=job.meta['fps'];step=max(1,round(fps/job.config['motion_fps']));anchor_frames=np.array([r['frame'] for r in anchors]);completed=0
    for start,end in job.intervals():
        path=folder/f'{start:09d}.npz';marker=path.with_suffix('.json')
        if valid_chunk(path,marker):completed+=1;continue
        if allowance(job,'motion')<=0:break
        with job.timed('motion'):
            last=None;last_index=None;records=[]
            # Include preceding grid point so chunk boundaries have the same optical link.
            begin=max(0,(start//step-1)*step)
            for index,t,frame in decode(job,begin,end):
                if index%step:continue
                gray=frame.to_ndarray(format='gray');h,w=gray.shape;gray=cv2.resize(gray,(job.config['motion_width'],round(h*job.config['motion_width']/w)))
                line=None
                if len(anchors):
                    pos=int(np.argmin(abs(anchor_frames-index)))
                    if abs(anchor_frames[pos]-index)/fps<job.config['max_anchor_gap_seconds']:line=anchors[pos].get('reference_line')
                if last is not None and index-last_index<=step*2:
                    info=rotation(last,gray,line,(index-last_index)/fps)
                else:info=dict(delta=0.,quality=0.,features=0,reason='decode_gap_or_start')
                if line is None:info['quality']=min(info['quality'],.2);info['reason']='no_visual_background_band'
                if index>=start:records.append((index,info['delta'],info['quality'],info['features']))
                last=gray;last_index=index
            a=np.asarray(records,float).reshape(-1,4);sha=write_npz(path,rows=a)
            save(marker,dict(sha256=sha,start=start,end=end,rows=len(a),signature=signature))
        completed+=1;job.status('motion','running',completed_chunks=completed,total_chunks=len(job.intervals()))
    job.status('motion','complete' if completed==len(job.intervals()) else 'budget_limited',completed_chunks=completed,total_chunks=len(job.intervals()))


def motion_rows(job):
    plan=load(job.out/'motion.json');rows=[]
    if plan:
        for path in sorted((job.out/plan['folder']).glob('*.npz')):
            if valid_chunk(path,path.with_suffix('.json')):
                with np.load(path) as z:rows.append(z['rows'])
    return np.concatenate(rows) if rows else np.empty((0,4))


def make_extra_sample(job,index):
    path=job.out/'images'/f'{index:09d}.jpg'
    if path.exists():return dict(frame=index,time=index/job.meta['fps'],image=str(path.relative_to(job.out)),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for i,t,frame in decode(job,index,min(job.meta['frames'],index+1)):
        return thumbnail(job,i,frame.to_ndarray(format='bgr24'))
    return None


def review_candidates(job,include_midpoints=False):
    anchors=chosen_observations(job);motion=motion_rows(job);scores={}
    for r in anchors:
        if r.get('error') or r.get('quality',0)<.4 or r.get('candidate_id') is None:scores[r['frame']]=2
    for a,b in zip(anchors,anchors[1:]):
        if a.get('angle') is None or b.get('angle') is None:continue
        between=motion[(motion[:,0]>a['frame'])&(motion[:,0]<=b['frame'])]
        reliable=len(between)>0 and np.mean(between[:,2]>.3)>.8
        residual=abs((b['angle']-a['angle']-between[:,1].sum()+90)%180-90)
        if residual>3 or not reliable:
            scores[b['frame']]=max(scores.get(b['frame'],0),1+min(10,residual))
            if include_midpoints and b['time']-a['time']>.6:scores[(a['frame']+b['frame'])//2]=1+min(10,residual)
    return sorted(scores,key=lambda k:(-scores[k],k))


def refine_pass(job,endpoint,model,stage):
    check_model(endpoint,model);indices=review_candidates(job,include_midpoints=stage=='refine')
    # Bound amplification: one extra primary pass, then one independent review pass.
    examined=0
    for n,index in enumerate(indices):
        if allowance(job,stage)<1:break
        with job.timed(stage):sample=make_extra_sample(job,index)
        if sample:observe(job,sample,endpoint,model,stage)
        examined=n+1
        if n%10==0:job.status(stage,'running',examined=n+1,planned=len(indices),model=model)
    job.status(stage,'complete' if examined==len(indices) else 'budget_limited',examined=len(observations(job,stage)),planned=len(indices),model=model)


def solve_segment(frames,motion,quality,anchors,fps):
    n=len(frames)
    if not anchors:return np.full(n,np.nan),np.zeros(n),np.full(n,np.inf)
    a_frames=np.array([a['frame'] for a in anchors]);values=np.unwrap(np.radians([a['angle'] for a in anchors])*2)/2*180/np.pi
    aw=np.zeros(n);ay=np.zeros(n)
    for a,value in zip(anchors,values):
        i=int(np.argmin(abs(frames-a['frame'])));weight=max(.01,a['quality'])/(9 if a.get('cue')=='shoreline' else 4)
        aw[i]+=weight;ay[i]+=weight*value
    # Relative motion is stronger than a perspective-biased individual shoreline anchor.
    weights=np.where(quality[1:]>.3,quality[1:]*4,.003)
    diagonal=aw.copy()+1e-7;diagonal[:-1]+=weights;diagonal[1:]+=weights
    rhs=ay.copy();rhs[:-1]-=weights*motion[1:];rhs[1:]+=weights*motion[1:]
    result=spsolve(diags([-weights,diagonal,-weights],[-1,0,1],format='csc'),rhs)
    nearest=np.searchsorted(a_frames,frames);left=np.clip(nearest-1,0,len(a_frames)-1);right=np.clip(nearest,0,len(a_frames)-1)
    distance=np.minimum(abs(frames-a_frames[left]),abs(frames-a_frames[right]))/fps
    local_quality=np.maximum(np.array([a['quality'] for a in anchors])[left],np.array([a['quality'] for a in anchors])[right])
    support=local_quality*np.exp(-distance/15)*np.where(quality>.3,1,.65)
    return result,support,distance


def export(job):
    start_time=time.monotonic();anchors=chosen_observations(job);valid=[a for a in anchors if a.get('angle') is not None and a.get('quality',0)>0]
    motion=motion_rows(job);fps=job.meta['fps'];step=max(1,round(fps/job.config['motion_fps']));frames=np.arange(0,job.meta['frames'],step)
    if not len(frames):raise ValueError('Video has no frames')
    delta=np.zeros(len(frames));quality=np.zeros(len(frames));have=np.zeros(len(frames),bool)
    for index,d,q,features in motion:
        i=int(index)//step
        if i<len(frames):delta[i]=d;quality[i]=q;have[i]=True
    # A long decode/processing hole is a hard boundary; short weak-motion intervals use low-weight interpolation.
    breaks=[0];missing=0
    for i,exists in enumerate(have):
        missing=0 if exists else missing+1
        if missing==max(2,round(fps/step)):breaks.extend([max(0,i-missing+1),i+1])
        elif missing>max(2,round(fps/step)):breaks.append(i+1)
    breaks=sorted(set(breaks+[len(frames)]));angles=np.full(len(frames),np.nan);confidence=np.zeros(len(frames));distance=np.full(len(frames),np.inf)
    for begin,end in zip(breaks,breaks[1:]):
        if begin==end:continue
        aa=[a for a in valid if frames[begin] <= a['frame'] < min(job.meta['frames'],frames[end-1]+step)]
        values,q,d=solve_segment(frames[begin:end],delta[begin:end],quality[begin:end],aa,fps);angles[begin:end]=values;confidence[begin:end]=q;distance[begin:end]=d
    unsupported=(distance>job.config['max_anchor_gap_seconds'])|(~have);angles[unsupported]=np.nan;confidence[unsupported]=0
    # Exact decode-validity masks: never bridge damaged source frames silently.
    decoded=np.zeros(job.meta['frames'],bool)
    for path in (job.out/'samples').glob('*.npz'):
        marker=valid_chunk(path,path.with_suffix('.json'))
        if marker:
            with np.load(path) as z:decoded[int(z['start']):int(z['end'])]=np.unpackbits(z['valid'])[:int(z['end'])-int(z['start'])].astype(bool)
    signature=digest(dict(version=1,source=job.config['source'],anchors=[(a['key'],a.get('angle'),a.get('quality')) for a in anchors],motion=load(job.out/'motion.json')))[:20]
    folder=job.out/'annotations'/signature;folder.mkdir(parents=True,exist_ok=True);shards=[];counts=dict(estimated=0,unknown=0,needs_review=0);review=[];sampled=[]
    for start,end in job.intervals():
        path=folder/f'{start:09d}.jsonl';tmp=path.with_suffix('.tmp')
        with tmp.open('w') as f:
            for index in range(start,end):
                l=min(index//step,len(frames)-1);r=min(l+1,len(frames)-1);fraction=(index-frames[l])/step;flags=[]
                known=np.isfinite(angles[l]) and (r==l or np.isfinite(angles[r])) and decoded[index]
                angle=float(angles[l]*(1-fraction)+angles[r]*fraction) if known else None
                q=float(min(confidence[l],confidence[r])) if known else 0.
                if not decoded[index]:flags.append('source_frame_missing_or_not_decoded')
                if not known:flags.append('no_supported_level')
                if known and min(quality[l],quality[r])<.3:flags.append('weak_background_motion')
                if known and q<.4:flags.append('low_evidence_quality')
                near=[a for a in anchors if a.get('needs_review') and abs(a['frame']-index)<fps*2]
                if near:flags.append('models_disagree')
                row=dict(frame=index,time_seconds=index/fps,correction_degrees_ccw=angle,evidence_quality=q,source='visual_and_background_motion' if known else 'unknown',flags=flags)
                f.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n');counts['estimated' if known else 'unknown']+=1;counts['needs_review']+=bool(flags)
                if index%max(1,job.meta['frames']//1200)==0:sampled.append(row)
                if flags:
                    if review and review[-1]['end_frame']==index-1 and review[-1]['flags']==flags:review[-1]['end_frame']=index
                    else:review.append(dict(start_frame=index,end_frame=index,flags=flags))
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path);shards.append(dict(path=str(path.relative_to(job.out)),start_frame=start,end_frame_exclusive=end,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest=dict(schema='video-leveling-annotations/v1',source=job.config['source'],video=job.config['video'],metadata=job.meta,coordinate_space='raw_source_image',angle_convention='Positive values rotate the raw image counterclockwise to level its inferred distant reference; OpenCV getRotationMatrix2D sign.',quality_semantics='Uncalibrated evidence quality, not probability of physical correctness.',status='complete_with_review_flags' if counts['unknown']==0 else 'partial',counts=counts,shards=shards,settings=job.config,models=load(job.out/'models.json'),created=time.time())
    save(job.out/'leveling.json',manifest);save(job.out/'review_intervals.json',review);save(job.out/'timeline_preview.json',sampled);job.charge('export',time.monotonic()-start_time);job.status('export','complete',**counts)
    make_report(job,manifest,anchors,sampled,review)
    return manifest


def make_report(job,manifest,anchors,sampled,review):
    import html
    points=' '.join(f'{r["time_seconds"]/job.meta["duration_seconds"]*1100:.1f},{150-r["correction_degrees_ccw"]*2:.1f}' for r in sampled if r['correction_degrees_ccw'] is not None)
    cards=[]
    for a in anchors[::max(1,len(anchors)//120)]:
        line=a.get('reference_line');overlay='' if not line else f'<line x1="{line[0]}" y1="{line[1]}" x2="{line[2]}" y2="{line[3]}" stroke="magenta" stroke-width="4"/>'
        cards.append(f'<article><h3>{a["time"]:.2f}s · {a["stage"]} · angle {a.get("angle")}</h3><svg viewBox="0 0 1000 1000" preserveAspectRatio="none" style="width:480px;aspect-ratio:16/9"><image href="{html.escape(a["image"])}" width="1000" height="1000" preserveAspectRatio="none"/>{overlay}</svg><p>{html.escape(a.get("note",a.get("error","")))}</p></article>')
    body=f'<meta charset="utf-8"><style>body{{font:16px sans-serif;margin:30px}}article{{display:inline-block;width:490px;vertical-align:top}}pre{{white-space:pre-wrap}}</style><h1>Standalone video leveling</h1><h2>{html.escape(Path(job.config["video"]).name)}</h2><p>Status: {manifest["status"]}. Angles are visual estimates, not calibrated gravity. Magenta lines show reference evidence.</p><pre>{html.escape(json.dumps(manifest["counts"],indent=2))}</pre><p><a href="leveling.json">Annotation manifest</a> · <a href="review_intervals.json">Review intervals</a> · <a href="state.json">Progress / budget</a></p><svg viewBox="0 0 1100 300" width="100%"><polyline points="{points}" fill="none" stroke="blue"/></svg>'+''.join(cards)
    (job.out/'report.html').write_text(body)
