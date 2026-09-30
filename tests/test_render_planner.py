import unittest
import numpy as np
from render_planner import plan,polygons,settings

class RenderPlannerTests(unittest.TestCase):
    def fixtures(self,n=180):
        meta=dict(frames=n,width=1920,height=1080,fps=30)
        c=dict(output_width=1280,output_height=720,margin_fraction=.1,subject_height_fraction=.55,minimum_crop_short_side=180)
        motion=dict(delta=np.zeros((n,2)).tolist(),quality=[dict(reliable=True)]*n,cuts=[],imu_calibration=dict(used=False))
        return c,meta,motion

    def test_abrupt_target_changes_keep_visibility_and_smooth_zoom(self):
        c,m,motion=self.fixtures();polys=[]
        for i in range(m['frames']):
            x=500 if i<90 else 1000;size=40 if i<90 else 150
            polys.append(np.array([[x,300],[x+size,300],[x+size,450],[x,450]]))
        result=plan(c,m,polys,[],np.linspace(-15,15,m['frames']),motion)
        self.assertGreater(min(r['target_retained_fraction'] for r in result['diagnostics']),.999)
        zoom=np.log(1080/np.array(result['extent']))
        self.assertLessEqual(max(abs(np.diff(zoom)))*30,np.log(2)/1.5+1e-8)
        self.assertLessEqual(max(abs(np.diff(zoom,2)))*900,.45+1e-8)
        self.assertGreaterEqual(min(result['extent']),180)

    def test_camera_translation_is_compensated_without_double_application(self):
        c,m,motion=self.fixtures(60);motion['delta']=[[0,0]]+[[3,0]]*59
        polys=[np.array([[500+i*3,300],[540+i*3,300],[540+i*3,360],[500+i*3,360]]) for i in range(60)]
        result=plan(c,m,polys,[],np.zeros(60),motion);center=np.array(result['centers'])
        np.testing.assert_allclose(np.diff(center,axis=0),np.tile([3,0],(59,1)),atol=1e-6)

    def test_magnification_amplifies_motion_and_forces_wider_framing(self):
        c,m,motion=self.fixtures(180)
        polys=[]
        for i in range(180):
            x=800+150*np.sin(i/8)
            polys.append(np.array([[x,300],[x+20,300],[x+20,330],[x,330]]))
        c['render_planner']=dict(center_speed=.15,center_acceleration=.3)
        result=plan(c,m,polys,[],np.zeros(180),motion)
        self.assertLessEqual(max(r['camera_speed_crop_per_second'] for r in result['diagnostics']),.15+1e-8)
        self.assertLessEqual(max(r['camera_acceleration_crop_per_second2'] for r in result['diagnostics']),.3+1e-8)
        self.assertGreater(max(result['extent']),180)

    def test_absence_and_single_frame_segments(self):
        c,m,motion=self.fixtures(3);motion['cuts']=[1,2]
        result=plan(c,m,[None]*3,[1],np.zeros(3),motion)
        self.assertTrue(np.isfinite(result['extent']).all())
        self.assertTrue(all(r['target_retained_fraction'] is None for r in result['diagnostics']))

    def test_manual_polygon_overrides_box_and_absence(self):
        _,m,_=self.fixtures(2);boxes=np.tile([1,2,3,4],(2,1))
        result,absent=polygons([],{'0':dict(source_polygon_px=[[1,1],[5,2],[2,8]]),'1':dict(bbox=None)},boxes,[True,True],m)
        self.assertEqual(result[0].shape,(3,2));self.assertIsNone(result[1]);self.assertEqual(absent,[1])
