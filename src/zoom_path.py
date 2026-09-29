"""Piecewise-linear zoom between accepted observations, without gap widening."""
import numpy as np
from verification_policy import accepted_row
from motion_render import motion_usable


def confident_frames(observations, corrections, count, threshold):
    rows = {r['frame']: dict(r) for r in observations}
    for frame, correction in corrections.items():
        frame = int(frame)
        if 'bbox' in correction:
            rows[frame] = dict(frame=frame, bbox=correction['bbox'], confidence=1,
                               visibility='visible' if correction['bbox'] is not None else 'absent')
    return np.array(sorted(frame for frame, r in rows.items()
        if 0 <= frame < count and r.get('bbox') is not None
        and (motion_usable(r) or r.get('confidence', 0) >= threshold)
        and r.get('visibility') not in ('absent', 'uncertain')
        and (motion_usable(r) or not r.get('error')) and not r.get('scene_cut')
        and (motion_usable(r) or r.get('box_verification',{}).get('version',0)<7 or accepted_row(r,threshold))), dtype=int)


def interpolate_zoom(crop_heights, source_height, anchors, endpoint_zoom):
    """Return crop heights for a linear *magnification* curve; endpoints take priority."""
    heights = np.asarray(crop_heights, dtype=float)
    if not len(heights):
        return heights.copy()
    if not np.isfinite(endpoint_zoom) or endpoint_zoom <= 0:
        raise ValueError('Endpoint zoom must be positive and finite')
    anchors = np.unique(np.asarray(anchors, dtype=int))
    anchors = anchors[(anchors > 0) & (anchors < len(heights)-1)]
    values = source_height / heights[anchors]
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError('Anchor crop heights must be positive and finite')
    frames = np.r_[0, anchors, len(heights)-1]
    zooms = np.r_[endpoint_zoom, values, endpoint_zoom]
    return source_height / np.interp(np.arange(len(heights)), frames, zooms)


def minimum_crop_size(aspect, short_side=180):
    if isinstance(short_side,bool) or not isinstance(short_side,(int,float)) or not np.isfinite(short_side) or short_side <= 0:raise ValueError('Minimum crop short side must be positive')
    if not np.isfinite(aspect) or aspect <= 0:raise ValueError('Invalid crop aspect ratio')
    return short_side*max(aspect,1),short_side*max(1/aspect,1)


def output_dimensions(config, meta):
    if not config.get('preserve_source_aspect',True):return config['output_width'],config['output_height']
    aspect=meta['width']/meta['height'];long=max(config['output_width'],config['output_height'])
    w,h=(long,long/aspect) if aspect>=1 else (long*aspect,long)
    return max(2,round(w/2)*2),max(2,round(h/2)*2)


def constrain_zoom(extent,centers,roll,source_size,output_size,subject_minimum,minimum_short_side=0):
    """Keep at least one complete output edge inside the source, with a diagnostic when subject fit conflicts.

    Extent is the output viewport height in source pixels. Larger means zooming out.
    A rectangle edge lies inside the source iff both inverse-mapped endpoints do.
    """
    w,h=source_size;ow,oh=output_size
    centers=np.asarray(centers,float);angle=np.deg2rad(roll)
    vertices=np.array([[-ow/oh/2,-.5],[ow/oh/2,-.5],[ow/oh/2,.5],[-ow/oh/2,.5]])
    cosine,sine=np.cos(angle),np.sin(angle)
    rays=np.empty((len(centers),4,2))
    rays[:,:,0]=cosine[:,None]*vertices[:,0]-sine[:,None]*vertices[:,1]
    rays[:,:,1]=sine[:,None]*vertices[:,0]+cosine[:,None]*vertices[:,1]
    distance=np.where(rays>0,np.array([w,h])-centers[:,None,:],centers[:,None,:])
    limits=np.full_like(rays,np.inf)
    np.divide(distance,np.abs(rays),out=limits,where=np.abs(rays)>1e-12)
    corner_limits=limits.min(axis=2)
    maximum=np.maximum(0,np.minimum(corner_limits,np.roll(corner_limits,-1,axis=1)).max(axis=1))
    minimum=np.maximum(np.asarray(subject_minimum,float),1.)
    conflict=minimum>maximum
    # Edge coverage takes priority when the subject-fit range is infeasible.
    constrained=np.minimum(np.maximum(minimum,extent),np.maximum(maximum,1.))
    if minimum_short_side:
        _,floor=minimum_crop_size(ow/oh,minimum_short_side)
        minimum=np.maximum(minimum,floor)
        conflict=minimum>maximum
        # Hard zoom cap takes precedence over edge coverage; fill missing borders.
        constrained=np.maximum(constrained,floor)
    return constrained,minimum,maximum,conflict
