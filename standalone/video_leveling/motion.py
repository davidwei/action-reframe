"""Background-band optical rotation, deliberately conservative about weak evidence."""
import math
import cv2
import numpy as np

def band_mask(shape,line=None):
    h,w=shape;mask=np.zeros((h,w),np.uint8)
    if line is None:mask[:int(h*.7)]=255
    else:
        x1,y1,x2,y2=np.array(line)*[w/1000,h/1000,w/1000,h/1000]
        xs=np.arange(w);ys=y1+(xs-x1)*(y2-y1)/max(1,x2-x1)
        mask[np.abs(np.arange(h)[:,None]-ys[None,:])<h*.12]=255
    mask[:4]=0;mask[-4:]=0;mask[:,:4]=0;mask[:,-4:]=0
    return mask

def rotation(previous,current,line=None,dt=.2):
    mask=band_mask(previous.shape,line);h,w=previous.shape;points=[]
    for col in range(6):
        region=mask.copy();region[:,:col*w//6]=0;region[:,(col+1)*w//6:]=0
        p=cv2.goodFeaturesToTrack(previous,40,.012,7,mask=region,blockSize=5)
        if p is not None:points.extend(p)
    if len(points)<15:return dict(delta=0.,quality=0.,features=len(points),reason='too_few_background_features')
    p=np.array(points,np.float32).reshape(-1,1,2)
    q,status,_=cv2.calcOpticalFlowPyrLK(previous,current,p,None,winSize=(21,21),maxLevel=3)
    if q is None:return dict(delta=0.,quality=0.,features=0,reason='flow_failed')
    back,reverse,_=cv2.calcOpticalFlowPyrLK(current,previous,q,None,winSize=(21,21),maxLevel=3)
    if back is None:return dict(delta=0.,quality=0.,features=0,reason='reverse_flow_failed')
    keep=(status.ravel()>0)&(reverse.ravel()>0)&(np.linalg.norm(back-p,axis=2).ravel()<1.5)
    a=p[keep].reshape(-1,2);b=q[keep].reshape(-1,2)
    if len(a)<12:return dict(delta=0.,quality=0.,features=len(a),reason='inconsistent_flow')
    matrix,inliers=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=1000,confidence=.99)
    if matrix is None:return dict(delta=0.,quality=0.,features=len(a),reason='no_robust_transform')
    good=inliers.ravel().astype(bool);n=int(good.sum());fraction=n/len(a);columns=len(set(np.minimum(5,(a[good,0]/w*6).astype(int))));span=float(np.ptp(a[good,0]))/w if n else 0.
    delta=math.degrees(math.atan2(matrix[1,0],matrix[0,0]));scale=float(np.hypot(matrix[0,0],matrix[1,0]))
    residual=float(np.median(np.linalg.norm((np.c_[a,np.ones(len(a))]@matrix.T)-b,axis=1)))
    reliable=n>=15 and fraction>=.65 and columns>=3 and span>=.35 and residual<=2 and abs(delta)<=120*dt and .9<scale<1.1
    quality=min(1,n/50)*fraction*min(1,span/.7) if reliable else 0.
    return dict(delta=delta if reliable else 0.,quality=quality,features=n,inlier_fraction=fraction,columns=columns,span=span,scale=scale,residual=residual,reason='background_motion' if reliable else 'weak_or_localized_motion')
