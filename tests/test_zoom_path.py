import unittest
import numpy as np
from zoom_path import confident_frames, interpolate_zoom


class ZoomPathTests(unittest.TestCase):
    def test_missing_intervals_interpolate_magnification_not_crop_height(self):
        heights=np.full(11,9999.)
        heights[2]=500;heights[8]=250
        zoom=1000/interpolate_zoom(heights,1000,[2,8],1.)
        np.testing.assert_allclose(zoom[[0,2,5,8,10]],[1,2,3,4,1])
        np.testing.assert_allclose(np.diff(zoom[2:9]),1/3)

    def test_endpoints_override_boxes_and_no_anchor_stays_full_view(self):
        np.testing.assert_allclose(interpolate_zoom([100]*5,1000,[0,4],1),[1000]*5)
        np.testing.assert_allclose(interpolate_zoom([100],1000,[0],1),[1000])
        np.testing.assert_allclose(interpolate_zoom([100]*5,1000,[],1),[1000]*5)

    def test_only_actual_confident_observations_and_human_corrections_anchor(self):
        rows=[dict(frame=i,bbox=[0,0,1,1],confidence=c) for i,c in [(0,.9),(2,.49),(4,.5),(6,.99)]]
        rows[-1]['error']='invalid response'
        corrections={'0':{'bbox':None},'3':{'bbox':[0,0,1,1]}}
        np.testing.assert_array_equal(confident_frames(rows,corrections,10,.5),[3,4])
