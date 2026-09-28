import unittest
import numpy as np
from label_geometry import preview_geometry,canonical_label,transform,box_polygon

class LabelGeometryTests(unittest.TestCase):
    def test_processed_selection_preserves_raw_polygon(self):
        geometry=preview_geometry({'output_width':1280,'output_height':720},{'width':1920,'height':1080},
                                  {'center':[960,540],'crop_height':600,'roll':25})
        points=box_polygon([500,250,650,430])
        label=canonical_label(points,'processed',geometry)
        self.assertEqual(label['selection_space'],'processed')
        np.testing.assert_allclose(label['processed_polygon_px'],points,atol=.001)
        self.assertNotAlmostEqual(label['source_polygon_px'][0][1],label['source_polygon_px'][1][1])
        restored=canonical_label(label['source_polygon_px'],'raw',geometry)
        np.testing.assert_allclose(restored['bbox'],label['bbox'],atol=.001)

    def test_clip_synthetic_border_and_reject_invalid_polygon(self):
        geometry=preview_geometry({}, {'width':100,'height':100})
        clipped=canonical_label(box_polygon([-10,-10,20,20]),'raw',geometry)
        self.assertEqual(clipped['bbox'],[0,0,20,20])
        for points in [box_polygon([-30,-30,-10,-10]),[[0,0],[10,10],[0,10],[10,0]],[[0,0],[1,float('nan')],[4,4]]]:
            with self.assertRaises(ValueError):canonical_label(points,'raw',geometry)

class PreviewLevelAvailabilityTests(unittest.TestCase):
    def test_unknown_level_does_not_claim_leveled(self):
        geometry=preview_geometry({},dict(width=100,height=80))
        self.assertEqual(geometry['mode'],'raw_full_frame')
        self.assertFalse(geometry['level_available']);self.assertIsNone(geometry['roll_degrees'])
        geometry=preview_geometry({},dict(width=100,height=80),roll=0)
        self.assertEqual(geometry['mode'],'leveled_full_frame');self.assertTrue(geometry['level_available'])
        geometry=preview_geometry({},dict(width=100,height=80),roll=9)
        self.assertEqual(geometry['roll_degrees'],9)
