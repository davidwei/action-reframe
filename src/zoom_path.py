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


def smoothing_settings(config):
    result=dict(zoom_seconds_per_doubling=config.get('zoom_seconds_per_doubling',.5),
                zoom_smoothing_seconds=config.get('zoom_smoothing_seconds',.15))
    for key,value in result.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or value<0 or (key=='zoom_seconds_per_doubling' and value==0):
            raise ValueError('Invalid zoom smoothing setting: '+key)
    return result


def smooth_zoom(extent, minimum_extent, fps, seconds_per_doubling=.5, smoothing_seconds=.15):
    """Offline log-zoom smoothing with a hard speed bound and look-ahead.

    Smooth log crop height (the negative of log zoom, up to a constant), then
    construct its least slope-bounded upper envelope in two linear passes.
    Raising crop height widens the view. Future fit requirements widen earlier
    frames; past requirements prevent snapping back in. Never clip this result
    to an edge-coverage limit afterward: use background fill instead.
    """
    from scipy.ndimage import gaussian_filter1d
    smoothing_settings(dict(zoom_seconds_per_doubling=seconds_per_doubling,zoom_smoothing_seconds=smoothing_seconds))
    values=np.asarray(extent,float);minimum=np.broadcast_to(np.asarray(minimum_extent,float),values.shape)
    if not np.isfinite(fps) or fps<=0:raise ValueError('FPS must be positive')
    if not np.isfinite(values).all() or not np.isfinite(minimum).all() or np.any(values<=0) or np.any(minimum<=0):
        raise ValueError('Crop extents must be positive and finite')
    if not len(values):return values.copy()
    log=np.log(values)
    if smoothing_seconds:log=gaussian_filter1d(log,smoothing_seconds*fps,mode='nearest')
    # Nominal endpoint framing is also a lower bound; transitions start/end wider if needed.
    bounds=np.log(minimum).copy();bounds[0]=max(bounds[0],np.log(values[0]));bounds[-1]=max(bounds[-1],np.log(values[-1]))
    log=np.maximum(log,bounds)
    step=np.log(2)/(fps*seconds_per_doubling)
    for i in range(1,len(log)):log[i]=max(log[i],log[i-1]-step)
    for i in range(len(log)-2,-1,-1):log[i]=max(log[i],log[i+1]-step)
    return np.exp(log)
