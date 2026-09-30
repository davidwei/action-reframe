"""Offline visibility-first framing using cached background motion and gyro attitude."""
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d, maximum_filter1d
from scipy.spatial.transform import Rotation
from zoom_path import minimum_crop_size

VERSION=2
DEFAULTS=dict(enabled=True,center_seconds=.5,zoom_seconds=.7,seconds_per_doubling=1.5,
              zoom_acceleration=.45,center_speed=.6,center_acceleration=1.2,gap_seconds=1.,motion_width=640)


def settings(c):
    options=dict(DEFAULTS,**c.get('render_planner',{}))
    for k,v in options.items():
        if k=='enabled':continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or v<=0:raise ValueError('Invalid render planner setting: '+k)
    return options


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
    size=(round(w*scale),round(h*scale));cap=cv2.VideoCapture(video);previous=None;mask_previous=None
    delta=np.zeros((n,2));reliable=np.zeros(n,bool);cuts=[];quality=[];prev_hist=None
    for i in range(n):
        ok,image=cap.read()
        if not ok:cap.release();raise RuntimeError(f'Camera-motion decode failed at {i}')
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
    cap.release()
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
    return dict(delta=delta.tolist(),quality=quality,cuts=cuts,imu_calibration=calibration)


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
        for k,poly in enumerate(p):
            if poly is None:required[k]=max(floor,h);continue
            # More room around unverified geometry is provided by the normal margin.
            offset=poly-smooth[k]
            frame_margin=c.get('_render_margins',[margin]*n)[start+k]
            required[k]=max(floor,2*np.abs(offset[:,1]).max()/(1-2*frame_margin),2*np.abs(offset[:,0]).max()/aspect/(1-2*frame_margin))
        # Widen to satisfy screen-relative translation speed and acceleration too.
        velocity=np.gradient(smooth,axis=0)*fps if count>1 else np.zeros_like(smooth)
        acceleration=np.gradient(velocity,axis=0)*fps if count>1 else np.zeros_like(smooth)
        required=np.maximum(required,np.linalg.norm(velocity/np.array([aspect,1]),axis=1)/opt['center_speed'])
        required=np.maximum(required,np.linalg.norm(acceleration/np.array([aspect,1]),axis=1)/opt['center_acceleration'])
        desired_size=required.copy()
        for k,poly in enumerate(p):
            if poly is not None:desired_size[k]=max(required[k],np.ptp(poly[:,1])/c['subject_height_fraction'])
        if start==0:desired_size[0]=max(h,desired_size[0])
        if stop==n:desired_size[-1]=max(h,desired_size[-1])
        # Smooth a look-ahead maximum envelope in log space. A uniform widening
        # restores containment; reducing amplitude about the widest view enforces
        # speed/acceleration without violating any visibility bound.
        base=np.log(desired_size)
        sigma=max(.5,opt['zoom_seconds']*fps)
        for attempt in range(30):
            # A maximum window covering the Gaussian support is a guaranteed
            # smooth majorant: every contributing neighbor includes this frame.
            radius=max(1,int(4*sigma+.5))
            log=gaussian_filter1d(maximum_filter1d(base,size=2*radius+1,mode='nearest'),sigma,mode='nearest')
            speed=np.max(abs(np.diff(log)))*fps if count>1 else 0
            accel=np.max(abs(np.diff(log,2)))*fps**2 if count>2 else 0
            if speed<=np.log(2)/opt['seconds_per_doubling']+1e-10 and accel<=opt['zoom_acceleration']+1e-10:break
            sigma*=1.25
        else:log=np.full(count,float(base.max()))
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
