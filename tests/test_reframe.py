import unittest
import cv2
import numpy as np
from reframe import camera_path, composite, corners, refine_level


class GeometryTests(unittest.TestCase):
    def test_rotated_edge_target_prioritizes_subject_fit_and_smooth_zoom(self):
        n=120
        meta={'frames':n,'width':1920,'height':1080,'fps':30}
        c={'output_width':1280,'output_height':720,'subject_height_fraction':.55,
           'margin_fraction':.12,'hold_seconds':.75,'widen_seconds':2.,'smoothing_seconds':.45}
        b=np.tile([0.,0.,300.,400.],(n,1))
        b[:,[0,2]]+=np.linspace(0,1500,n)[:,None]
        roll=np.linspace(-65,65,n)
        centers,ext=camera_path(c,meta,b,np.ones(n,bool),roll)
        self.assertLessEqual(np.max(np.abs(np.diff(np.log(ext)))),np.log(2)/(30*.5)+1e-9)
        self.assertGreaterEqual(ext.min(),180-1e-8)
        for i in range(n):
            m=cv2.getRotationMatrix2D(tuple(centers[i]),float(roll[i]),720/ext[i])
            m[:,2]+=np.array([640,360])-centers[i]
            subject=corners(b[i])@m[:,:2].T+m[:,2]
            self.assertTrue(((subject>=-1e-6)&(subject<=np.array([1280,720])+1e-6)).all())

    def test_missing_target_widens_and_starts_full_view(self):
        n=240;meta={'frames':n,'width':1920,'height':1080,'fps':30}
        c={'output_width':1280,'output_height':720,'subject_height_fraction':.55,
           'margin_fraction':.12,'hold_seconds':.75,'widen_seconds':2.,'smoothing_seconds':.1}
        b=np.tile([600.,300.,650.,380.],(n,1));valid=np.zeros(n,bool);valid[30:60]=True
        center,ext=camera_path(c,meta,b,valid,np.zeros(n))
        self.assertAlmostEqual(ext[0],1080,delta=1)
        self.assertGreater(ext[-1],ext[65]*3)
        self.assertTrue(np.allclose(center[-1],[960,540],atol=1))

    def test_blurred_extension_has_no_black_holes(self):
        frame=np.full((100,200,3),120,np.uint8)
        m=cv2.getRotationMatrix2D((100,50),35,.8)
        out=composite(frame,m,(200,100),15)
        self.assertEqual(out.shape,frame.shape)
        self.assertGreaterEqual(out.min(),119)

    def test_roll_sign_levels_a_sloping_line(self):
        f=np.full((540,960,3),200,np.uint8)
        cv2.line(f,(0,150),(959,350),(10,10,10),3)
        angle,ok=refine_level(f,[0,150/540*1000,1000,350/540*1000])
        self.assertTrue(ok)
        m=cv2.getRotationMatrix2D((480,270),angle,1)
        points=np.array([[0,150],[959,350]])@m[:,:2].T+m[:,2]
        self.assertLess(abs(points[1,1]-points[0,1]),5)


if __name__=='__main__':
    unittest.main()
