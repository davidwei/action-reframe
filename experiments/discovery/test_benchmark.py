import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from experiments.discovery import benchmark

class GeometryTests(unittest.TestCase):
    def test_round_trip_rotated_box(self):
        import numpy as np
        matrix,size=benchmark.dual_tracking.expanded_rotation(1920,1080,23)
        box=[300,250,460,430]
        raw,polygon=benchmark.dual_tracking.source_box(box,matrix,size,[1920,1080])
        view=benchmark.dual_tracking.transform_points(polygon,matrix)
        expected=benchmark.dual_tracking.box_points(np.array(box)*np.tile(size,2)/1000)
        np.testing.assert_allclose(view,expected,atol=1e-8)

if __name__=='__main__':unittest.main()
