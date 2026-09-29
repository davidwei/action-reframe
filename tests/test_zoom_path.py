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

    def test_rotation_limits_preserve_one_full_edge_and_subject(self):
        from zoom_path import constrain_zoom
        centers=np.array([[960,540],[1501.363233,219.04262]])
        heights,minimum,maximum,conflicts=constrain_zoom([3000,992.493743],centers,[0,9.875842],(1920,1080),(1280,720),[100,100])
        self.assertAlmostEqual(heights[0],1080)
        self.assertLess(heights[1],992.493743)
        self.assertFalse(conflicts.any())
        import cv2
        for i in range(2):
            r=cv2.getRotationMatrix2D((0,0),[0,9.875842][i],1)[:,:2]
            points=np.array([[-16/9/2,-.5],[16/9/2,-.5],[16/9/2,.5],[-16/9/2,.5]])*heights[i]@r+centers[i]
            inside=((points>=-1e-6)&(points<=np.array([1920,1080])+1e-6)).all(axis=1)
            self.assertTrue(any(inside[j] and inside[(j+1)%4] for j in range(4)))
        heights,_,_,conflicts=constrain_zoom([3000],centers[:1],[0],(1920,1080),(1280,720),[1500])
        self.assertEqual(heights[0],1080);self.assertTrue(conflicts[0])

    def test_log_zoom_bound_lookahead_and_subject_fit(self):
        from zoom_path import smooth_zoom
        fps=30;extent=np.r_[np.full(30,210.6),np.full(30,331.6)]
        minimum=np.r_[np.full(30,180.),np.full(30,300.)]
        result=smooth_zoom(extent,minimum,fps,.5,.15)
        self.assertTrue(np.all(result>=minimum-1e-8))
        self.assertLessEqual(np.max(np.abs(np.diff(np.log(result)))),np.log(2)/15+1e-10)
        self.assertGreater(result[29],extent[29])  # Widen before the larger box arrives.
        self.assertLess(result[30]/result[29],1.05)
        # Reversing the clip preserves the symmetric speed/fit contract.
        reverse=smooth_zoom(extent[::-1],minimum[::-1],fps,.5,.15)
        np.testing.assert_allclose(reverse,result[::-1])

    def test_single_frame_peak_and_aspect_independent_speed_bound(self):
        from zoom_path import smooth_zoom
        desired=np.full(101,180.);minimum=desired.copy();minimum[50]=720
        result=smooth_zoom(desired,minimum,60,.5,0)
        self.assertGreaterEqual(result[50],720-1e-8)
        self.assertGreater(result[49],180);self.assertGreater(result[51],180)
        self.assertLessEqual(np.max(np.abs(np.diff(np.log(result)))),np.log(2)/30+1e-10)
        np.testing.assert_allclose(smooth_zoom([180],[180],30),[180])
        for value in [0,-1,float('nan')]:
            with self.assertRaises(ValueError):smooth_zoom([180],[180],30,value)
