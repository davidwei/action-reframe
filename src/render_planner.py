"""Offline visibility-first framing using cached background motion and gyro attitude."""
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from scipy.spatial.transform import Rotation
from zoom_path import minimum_crop_size

VERSION=3  # Polygon preparation, background motion, and repaired-source evidence.
# Independent from motion evidence: bump whenever camera-path behavior changes.
# Version 6 forced the video endpoints to a full-source-height crop even when
# tracking was present there.  Version 7 frames tracked boundaries from the
# object and gives genuinely untracked tails a bounded, gradual transition.
CAMERA_PATH_VERSION=7
DEFAULTS=dict(enabled=True,center_seconds=.5,zoom_seconds=.7,seconds_per_doubling=1.5,
              zoom_acceleration=.45,center_speed=.6,center_acceleration=1.2,gap_seconds=1.,motion_width=640,
              tracked_boundary_scale=1.5)


def settings(c):
    options=dict(DEFAULTS,**c.get('render_planner',{}))
    for k,v in options.items():
        if k=='enabled':continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or v<=0:raise ValueError('Invalid render planner setting: '+k)
    return options


def _smooth_tracked_log(base, fps, options):
    """Smooth one tracked interval without letting untracked tails widen it."""
    sigma=max(.5,options['zoom_seconds']*fps)
    for _ in range(30):
        radius=max(1,int(4*sigma+.5))
        result=gaussian_filter1d(maximum_filter1d(base,size=2*radius+1,mode='nearest'),sigma,mode='nearest')
        speed=np.max(abs(np.diff(result)))*fps if len(result)>1 else 0
        accel=np.max(abs(np.diff(result,2)))*fps**2 if len(result)>2 else 0
        if speed<=np.log(2)/options['seconds_per_doubling']+1e-10 and accel<=options['zoom_acceleration']+1e-10:
            return result
        sigma*=1.25
    return np.full(len(base),float(np.max(base)))


def _tail_log(boundary, frames, fps, direction, source_extent, options):
    """Ease an untracked tail toward a wider view within speed/acceleration limits."""
    if frames<=0:return np.empty(0)
    duration=frames/fps
    maximum_delta=max(0.,np.log(max(source_extent,np.exp(boundary)))-boundary)
    maximum_delta=min(maximum_delta,
        np.log(2)/options['seconds_per_doubling']*duration/1.5,
        options['zoom_acceleration']*duration**2/6)
    wide=boundary+maximum_delta
    if direction=='prefix':
        u=np.arange(frames,dtype=float)/frames
        ease=u*u*(3-2*u)
        return wide+(boundary-wide)*ease
    u=np.arange(1,frames+1,dtype=float)/frames
    ease=u*u*(3-2*u)
    return boundary+(wide-boundary)*ease


def polygons(observations,corrections,boxes,supported,meta):
    n=meta['frames'];by={r['frame']:r for r in observations};result=[];absent=[]
    for i in range(n):
        row=by.get(i,{});label=corrections.get(str(i),{})
        if 'bbox' in label and label['bbox'] is None:absent.append(i);result.append(None);continue
        poly=label.get('source_polygon_px') or (row.get('source_polygon_px') if supported[i] else None)
        if poly is None and supported[i]:
            x1,y1,x2,y2=boxes[i];poly=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        if poly is not None:
            poly=np.asarray(poly,float)
            if poly.ndim!=2 or poly.shape[1]!=2 or len(poly)<3 or not np.isfinite(poly).all():poly=None
            else:
                source=np.array([[0,0],[meta['width'],0],[meta['width'],meta['height']],[0,meta['height']]],np.float32)
                area,clipped=cv2.intersectConvexConvex(cv2.convexHull(poly.astype(np.float32)),source)
                poly=clipped.reshape(-1,2).astype(float) if clipped is not None and area>1 else None
        result.append(poly)
    return result,absent


def background_motion(video,meta,polys,gyro,options):
    """Estimate residual translation AFTER gyro roll, never apply attitude twice.

    IMU pitch/yaw deltas are fitted to observed background translation; use only
    a held-out validated fit, and never extrapolate it across unsupported frames.
    """
    n=meta['frames'];w,h=meta['width'],meta['height'];scale=min(1,options['motion_width']/w)
    size=(round(w*scale),round(h*scale));previous=None;mask_previous=None
    delta=np.zeros((n,2));reliable=np.zeros(n,bool);cuts=[];quality=[];prev_hist=None;repairs=[]
    from source_decode import frames as source_frames
    for decoded in source_frames(video,meta):
        i,image=decoded.index,decoded.image
        if decoded.repaired:
            repairs.append(decoded.repair());previous=None;mask_previous=None;prev_hist=None
            quality.append(dict(frame=i,reliable=False,features=0,inlier_ratio=0.,error_px=None,scene_cut=False,source_frame_repaired=True))
            continue
        gray=cv2.cvtColor(cv2.resize(image,size),cv2.COLOR_BGR2GRAY)
        angle=gyro['frames'][i]['roll'] if gyro else 0.
        matrix=cv2.getRotationMatrix2D((size[0]/2,size[1]/2),angle,1)
        leveled=cv2.warpAffine(gray,matrix,size)
        mask=cv2.warpAffine(np.full(size[::-1],255,np.uint8),matrix,size)
        mask=cv2.erode(mask,np.ones((15,15),np.uint8))
        if polys[i] is not None:
            pts=cv2.transform((polys[i]*scale).astype(np.float32)[None],matrix)[0]
            target=np.zeros_like(mask);cv2.fillConvexPoly(target,np.rint(pts).astype(np.int32),255)
            mask[cv2.dilate(target,np.ones((25,25),np.uint8))>0]=0
        hist=cv2.calcHist([gray],[0],None,[32],[0,256]);cv2.normalize(hist,hist)
        cut=prev_hist is not None and cv2.compareHist(prev_hist,hist,cv2.HISTCMP_BHATTACHARYYA)>.65
        good_count=0;ratio=0.;error=None
        if previous is not None and not cut:
            points=cv2.goodFeaturesToTrack(previous,240,.015,8,mask=mask_previous)
            if points is not None and len(points)>=16:
                nxt,status,_=cv2.calcOpticalFlowPyrLK(previous,leveled,points,None)
                if nxt is not None:
                    back,back_status,_=cv2.calcOpticalFlowPyrLK(leveled,previous,nxt,None)
                    if back is not None:
                        valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<1.)
                        q=nxt.reshape(-1,2);inside=(q[:,0]>=0)&(q[:,0]<size[0])&(q[:,1]>=0)&(q[:,1]<size[1])
                        valid &= inside
                        idx=np.flatnonzero(valid)
                        if len(idx):valid[idx] &= mask[q[idx,1].astype(int),q[idx,0].astype(int)]>0
                        old=points.reshape(-1,2)[valid];new=q[valid]
                        if len(old)>=16:
                            a,inliers=cv2.estimateAffinePartial2D(old,new,method=cv2.RANSAC,ransacReprojThreshold=2)
                            if a is not None:
                                good=inliers.ravel().astype(bool);good_count=int(good.sum());ratio=float(good.mean())
                                spread=np.ptp(old[good],axis=0) if good_count else [0,0]
                                predicted=cv2.transform(old[None],a)[0];error=float(np.median(np.linalg.norm(predicted[good]-new[good],axis=1))) if good_count else None
                                if good_count>=20 and ratio>=.65 and min(spread/np.array(size))>.2 and .97<np.hypot(a[0,0],a[0,1])<1.03:
                                    center=np.array(size)/2;delta[i]=(a[:,:2]@center+a[:,2]-center)/scale;reliable[i]=True
        if cut:cuts.append(i)
        quality.append(dict(frame=i,reliable=bool(reliable[i]),features=good_count,inlier_ratio=ratio,error_px=error,scene_cut=bool(cut)))
        previous=leveled;mask_previous=mask;prev_hist=hist
    calibration=dict(used=False,reason='Insufficient validated attitude/image agreement')
    if gyro and all('quaternion_wxyz' in r for r in gyro['frames']):
        q=np.array([r['quaternion_wxyz'] for r in gyro['frames']]);rot=Rotation.from_quat(q[:,[1,2,3,0]])
        angular=np.zeros((n,3));angular[1:]=(rot[:-1].inv()*rot[1:]).as_rotvec()
        ids=np.flatnonzero(reliable);train=ids[::2];test=ids[1::2]
        if len(test)>=30:
            coeff=np.linalg.lstsq(angular[train],delta[train],rcond=None)[0];prediction=angular@coeff
            baseline=float(np.mean(np.sum(delta[test]**2,axis=1)));mse=float(np.mean(np.sum((prediction[test]-delta[test])**2,axis=1)))
            score=1-mse/max(baseline,1e-9);used=score>=.7
            calibration=dict(used=used,heldout_explained_motion=score,samples=len(ids),coefficients=coeff.tolist(),reason='Empirical attitude-to-image fit; zero-frame timestamp offset; no intrinsic calibration')
            if used:delta[reliable]=.8*delta[reliable]+.2*prediction[reliable]
    return dict(delta=delta.tolist(),quality=quality,cuts=cuts,imu_calibration=calibration,source_repairs=repairs)


def plan(c,meta,polys,absent,roll,motion):
    opt=settings(c);n=meta['frames'];fps=meta['fps'];w,h=meta['width'],meta['height'];aspect=c['output_width']/c['output_height'];margin=c['margin_fraction']
    if not 0<=margin<.5:raise ValueError('Invalid framing margin')
    _,floor=minimum_crop_size(aspect,c.get('minimum_crop_short_side',180))
    center=np.empty((n,2));extent=np.empty(n);diagnostics=[];screen_velocity=np.zeros((n,2));screen_acceleration=np.zeros((n,2))
    # Reset at cuts; no camera trajectory is interpolated across unrelated scenes.
    boundaries=sorted(set([0,n]+motion['cuts']));rays=np.array([cv2.getRotationMatrix2D((0,0),float(a),1)[:,:2] for a in roll]);origin=np.array([w/2,h/2])
    for start,stop in zip(boundaries,boundaries[1:]):
        count=stop-start;grid=np.arange(count);bg=np.cumsum(np.array(motion['delta'])[start:stop],axis=0);bg-=bg[0]
        p=[None if poly is None else (poly-origin)@rays[i].T-bg[i-start] for i,poly in enumerate(polys[start:stop],start)]
        valid=np.array([v is not None for v in p]);ids=np.flatnonzero(valid)
        if len(ids):
            targets=np.array([v.mean(axis=0) for v in p if v is not None]);desired=np.column_stack([np.interp(grid,ids,targets[:,j]) for j in (0,1)])
            # Long unsupported gaps gradually return toward the source center.
            distance=np.min(abs(grid[:,None]-ids[None,:]),axis=1)/fps
            blend=np.clip((distance-c.get('hold_seconds',.7))/opt['gap_seconds'],0,1)
            for i in absent:
                if start<=i<stop:blend[i-start]=1
            desired=desired*(1-blend[:,None])-bg*blend[:,None]
        else:desired=-bg
        smooth=gaussian_filter1d(desired,max(.5,opt['center_seconds']*fps),axis=0,mode='nearest')
        required=np.full(count,floor)
        object_extent=np.full(count,np.nan)
        for k,poly in enumerate(p):
            if poly is None:continue
            # More room around unverified geometry is provided by the normal margin.
            offset=poly-smooth[k]
            frame_margin=c.get('_render_margins',[margin]*n)[start+k]
            required[k]=max(floor,2*np.abs(offset[:,1]).max()/(1-2*frame_margin),2*np.abs(offset[:,0]).max()/aspect/(1-2*frame_margin))
            object_extent[k]=max(np.ptp(poly[:,1]),np.ptp(poly[:,0])/aspect)
        # Widen to satisfy screen-relative translation speed and acceleration too.
        velocity=np.gradient(smooth,axis=0)*fps if count>1 else np.zeros_like(smooth)
        acceleration=np.gradient(velocity,axis=0)*fps if count>1 else np.zeros_like(smooth)
        required=np.maximum(required,np.linalg.norm(velocity/np.array([aspect,1]),axis=1)/opt['center_speed'])
        required=np.maximum(required,np.linalg.norm(acceleration/np.array([aspect,1]),axis=1)/opt['center_acceleration'])
        if len(ids):
            # Use object-relative framing wherever tracking is present.  This
            # makes the first/last tracked positions stable anchors rather than
            # letting the former full-view endpoint rule dominate them.
            # Visibility, motion, and minimum-crop requirements may widen this
            # nominal 1.5x framing when necessary.
            boundary_scale=opt['tracked_boundary_scale']
            tracked=np.maximum(required[ids],object_extent[ids]*boundary_scale)
            desired_size=np.exp(np.interp(grid,ids,np.log(tracked)))
            desired_size=np.maximum(desired_size,required)
        else:
            desired_size=np.maximum(required,h)
        # Smooth only the tracked interval.  Otherwise a wide untracked endpoint
        # enters the maximum-filter window and flattens the intended tail zoom.
        if len(ids):
            first,last=ids[0],ids[-1]
            log=np.empty(count)
            log[first:last+1]=_smooth_tracked_log(np.log(desired_size[first:last+1]),fps,opt)
            log[:first]=_tail_log(log[first],first,fps,'prefix',h,opt)
            log[last+1:]=_tail_log(log[last],count-last-1,fps,'suffix',h,opt)
            # Motion-derived visibility bounds still take priority.  Propagate
            # any raised bounds backward/forward at the hard zoom-speed limit.
            log=np.maximum(log,np.log(required))
            step=np.log(2)/(fps*opt['seconds_per_doubling'])
            for k in range(1,count):log[k]=max(log[k],log[k-1]-step)
            for k in range(count-2,-1,-1):log[k]=max(log[k],log[k+1]-step)
        else:
            log=np.log(desired_size)
        extent[start:stop]=np.exp(log)
        # Recheck acceleration including changes in magnification itself.
        screen=velocity/(extent[start:stop,None]*np.array([aspect,1]))
        screen_acc=np.gradient(screen,axis=0)*fps if count>1 else np.zeros_like(screen)
        widen=max(1,float(np.linalg.norm(screen,axis=1).max())/opt['center_speed'],float(np.linalg.norm(screen_acc,axis=1).max())/opt['center_acceleration'])
        extent[start:stop]*=widen
        screen_velocity[start:stop]=screen/widen;screen_acceleration[start:stop]=screen_acc/widen
        for k,i in enumerate(range(start,stop)):center[i]=rays[i].T@(smooth[k]+bg[k])+origin
    for i,poly in enumerate(polys):
        matrix=cv2.getRotationMatrix2D(tuple(center[i]),float(roll[i]),meta['height']/extent[i]);offset=None;retained=None
        if poly is not None:
            q=(poly-center[i])@rays[i].T;position=q/[extent[i]*aspect,extent[i]]+.5;offset=(position.mean(axis=0)-.5).tolist()
            hull=cv2.convexHull(position.astype(np.float32));area=cv2.contourArea(hull)
            overlap,_=cv2.intersectConvexConvex(hull,np.array([[0,0],[1,0],[1,1],[0,1]],np.float32));retained=min(1,float(overlap/max(area,1e-12)))
        diagnostics.append(dict(target_retained_fraction=retained,target_offset_fraction=offset,motion_reliable=motion['quality'][i]['reliable'],scene_cut=i in motion['cuts']))
    zoom=np.log(h/extent)
    for i,d in enumerate(diagnostics):
        d['camera_speed_crop_per_second']=float(np.linalg.norm(screen_velocity[i]))
        d['camera_acceleration_crop_per_second2']=float(np.linalg.norm(screen_acceleration[i]))
        d['zoom_velocity']=float((zoom[i]-zoom[i-1])*fps) if i else 0.
        d['zoom_acceleration']=float((zoom[i]-2*zoom[i-1]+zoom[i-2])*fps**2) if i>1 else 0.
    if not np.isfinite(center).all() or not np.isfinite(extent).all():raise ValueError('Nonfinite camera path')
    if any(d['target_retained_fraction'] is not None and d['target_retained_fraction']<.995 for d in diagnostics):raise ValueError('Camera path violates target visibility')
    return dict(centers=center.tolist(),extent=extent.tolist(),diagnostics=diagnostics,imu_calibration=motion['imu_calibration'])
