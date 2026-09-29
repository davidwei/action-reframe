"""Canonical source polygons and exact processed-preview coordinate transforms."""
import hashlib
import json
import cv2
import numpy as np


def box_polygon(box):
    x1,y1,x2,y2=box
    return [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]


def transform(points,matrix):
    points=np.asarray(points,float)
    return (np.c_[points,np.ones(len(points))]@np.asarray(matrix).T).tolist()


def preview_geometry(config,meta,track=None,roll=None):
    from dual_tracking import expanded_rotation
    if track and track.get('center') is not None and track.get('crop_height',0)>0:
        width,height=track.get('render_size',[int(config.get('output_width',1280)),int(config.get('output_height',720))])
        center=np.asarray(track['center'],float)
        matrix=cv2.getRotationMatrix2D(tuple(center),float(track.get('roll',0)),height/track['crop_height'])
        matrix[:,2]+=np.array([width/2,height/2])-center
        mode='saved_render';roll=float(track.get('roll',0))
    else:
        matrix,(width,height)=expanded_rotation(meta['width'],meta['height'],roll if roll is not None else 0)
        mode='leveled_full_frame' if roll is not None else 'raw_full_frame'
    result=dict(source_to_view=matrix.tolist(),view_to_source=cv2.invertAffineTransform(matrix).tolist(),
                width=int(width),height=int(height),source_width=meta['width'],source_height=meta['height'],mode=mode,roll_degrees=roll,level_available=roll is not None)
    result['signature']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:20]
    return result


def canonical_label(points,space,geometry):
    if space not in ('raw','processed'):raise ValueError('Unknown selection space')
    points=np.asarray(points,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or not 3<=len(points)<=16 or not np.isfinite(points).all():raise ValueError('Invalid polygon')
    if not cv2.isContourConvex(points.astype(np.float32)):raise ValueError('Selection polygon must be convex')
    if space=='processed':points=np.asarray(transform(points,geometry['view_to_source']))
    source_rect=np.array(box_polygon([0,0,geometry['source_width'],geometry['source_height']]),np.float32)
    area,clipped=cv2.intersectConvexConvex(points.astype(np.float32),source_rect)
    if clipped is None or area<1:raise ValueError('Selection contains no original-image pixels; blurred extension is not source content')
    polygon=clipped.reshape(-1,2).astype(float)
    box=np.r_[polygon.min(axis=0),polygon.max(axis=0)].tolist()
    return dict(bbox=box,source_polygon_px=polygon.tolist(),processed_polygon_px=transform(polygon,geometry['source_to_view']),
                selection_space=space,view_polygon_px=points.tolist() if space=='raw' else transform(points,geometry['source_to_view']),
                preview_geometry=geometry,confidence_source='human')


def human_crop(image,record):
    """Preserve the selected polygon's contents inside its rectangular image crop."""
    h,w=image.shape[:2]
    box=np.asarray(record['bbox'])*[w,h,w,h]/1000
    x1,y1=np.maximum(0,np.floor(box[:2])).astype(int)
    x2,y2=np.minimum([w,h],np.ceil(box[2:])).astype(int)
    crop=image[y1:y2,x1:x2].copy()
    polygon=record.get('source_polygon_px')
    if polygon and crop.size:
        mask=np.zeros(crop.shape[:2],np.uint8)
        cv2.fillConvexPoly(mask,np.rint(np.asarray(polygon)-[x1,y1]).astype(np.int32),255)
        crop[mask==0]=0
    return crop
