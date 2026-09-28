"""Piecewise-linear zoom between accepted observations, without gap widening."""
import numpy as np
from verification_policy import accepted_row


def confident_frames(observations, corrections, count, threshold):
    rows = {r['frame']: dict(r) for r in observations}
    for frame, correction in corrections.items():
        frame = int(frame)
        if 'bbox' in correction:
            rows[frame] = dict(frame=frame, bbox=correction['bbox'], confidence=1,
                               visibility='visible' if correction['bbox'] is not None else 'absent')
    return np.array(sorted(frame for frame, r in rows.items()
        if 0 <= frame < count and r.get('bbox') is not None
        and r.get('confidence', 0) >= threshold
        and r.get('visibility') not in ('absent', 'uncertain')
        and not r.get('error') and not r.get('scene_cut')
        and (r.get('box_verification',{}).get('version',0)<7 or accepted_row(r,threshold))), dtype=int)


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
