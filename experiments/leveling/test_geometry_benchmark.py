import importlib.util,sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from geometry_benchmark import direction
from leveling import line_angle
import cv2,numpy as np

class DirectionTests(unittest.TestCase):
    def test_downward_y_sign_and_rotation(self):
        self.assertEqual(direction(line_angle([0,200,1000,400],1280,720)),'falls_right')
        self.assertEqual(direction(line_angle([0,400,1000,200],1280,720)),'rises_right')
        self.assertEqual(direction(None),'unknown')
        self.assertEqual(direction(1),'horizontal')
        a=np.array([[0.,200.],[1000.,400.]])
        before=np.degrees(np.arctan2(*(a[1]-a[0])[::-1]))
        matrix=cv2.getRotationMatrix2D((500,300),10,1)
        b=np.c_[a,np.ones(2)]@matrix.T
        after=np.degrees(np.arctan2(*(b[1]-b[0])[::-1]))
        self.assertAlmostEqual(after-before,-10)
if __name__=='__main__':unittest.main()
