"""Local CPU optical-flow proposals; reliability is separate from object identity."""
import cv2
import numpy as np


class VisualTracker:
    def initialize(self, image, box, polygon=None):
        self.gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        self.box=np.asarray(box,dtype=float)
        x1,y1,x2,y2=self.box
        self.corners=np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]])
        mask=np.zeros(self.gray.shape,np.uint8)
        x1,y1=np.floor(self.box[:2]).astype(int);x2,y2=np.ceil(self.box[2:]).astype(int)
        mask[max(0,y1):max(0,y2),max(0,x1):max(0,x2)]=255
        if polygon:
            mask[:]=0;cv2.fillConvexPoly(mask,np.rint(polygon).astype(np.int32),255)
        self.points=cv2.goodFeaturesToTrack(self.gray,80,.01,3,mask=mask,blockSize=3)
        self.uncertainty=0.
        return self

    def update(self,image):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        if self.points is None or len(self.points)<4:
            return self._lost('Too few target features')
        params=dict(winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
        nxt,status,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,None,**params)
        if nxt is None:return self._lost('Optical flow unavailable')
        back,reverse,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,nxt,None,**params)
        if back is None:return self._lost('Reverse flow unavailable')
        residual=np.linalg.norm(back-self.points,axis=2).ravel()
        valid=(status.ravel()>0)&(reverse.ravel()>0)&np.isfinite(residual)&(residual<1.5)
        old=self.points.reshape(-1,2)[valid];new=nxt.reshape(-1,2)[valid]
        if len(old)<4:return self._lost('Forward/backward flow inconsistent')
        matrix,inliers=cv2.estimateAffinePartial2D(old,new,method=cv2.RANSAC,ransacReprojThreshold=2)
        if matrix is None or inliers is None:return self._lost('No consistent target motion')
        good=inliers.ravel().astype(bool);scale=float(np.hypot(matrix[0,0],matrix[0,1]))
        if good.sum()<4 or not .8<=scale<=1.25:return self._lost('Unreliable scale or motion')
        moved=np.c_[self.corners,np.ones(4)]@matrix.T
        h,w=gray.shape
        box=np.r_[np.maximum(moved.min(axis=0),0),np.minimum(moved.max(axis=0),[w,h])]
        if np.any(box[2:]<=box[:2]):return self._lost('Target left the image')
        quality=float(good.sum()/len(self.points))
        if quality<.25:return self._lost('Too few original features remain')
        self.corners=moved
        self.uncertainty+=float(np.median(residual[valid][good]))+.15
        self.box=box;self.gray=gray;self.points=new[good].reshape(-1,1,2)
        return dict(box=box.tolist(),motion_quality=quality,uncertainty_px=self.uncertainty,
                    feature_count=int(good.sum()),reliable=True)

    def _lost(self,reason):
        return dict(box=self.box.tolist(),motion_quality=0.,uncertainty_px=self.uncertainty,
                    feature_count=0,reliable=False,reason=reason)


def relaxed_box(box,shape,uncertainty=0.,reliable=True,padding_fraction=.15,min_padding_px=8):
    box=np.asarray(box,float);size=box[2:]-box[:2]
    padding=np.maximum(size*padding_fraction,min_padding_px)+uncertainty
    if not reliable:padding=np.maximum(padding,size*.3)+min_padding_px
    h,w=shape[:2]
    return np.r_[np.maximum(0,box[:2]-padding),np.minimum([w,h],box[2:]+padding)].tolist()


def too_large(region,localized,max_dimension=1.5,max_area=2.):
    size=np.maximum(np.asarray(region)[2:]-region[:2],1)
    base=np.maximum(np.asarray(localized)[2:]-localized[:2],1)
    return bool(np.any(size/base>max_dimension) or np.prod(size)/np.prod(base)>max_area)
