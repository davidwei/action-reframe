import tempfile
import unittest
from pathlib import Path
import numpy as np
from temporal_context import directional_records, context_key, build_context
from backward_tracking import backward_pass
from reframe import set_analysis_fps


def row(frame, **extra):
    return dict(frame=frame,time=frame/30,bbox=[100,200,200,400],confidence=.9,visibility='visible',
                shoreline=[0,500,1000,250],level_confidence=.8,note='previous observation',**extra)


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.meta={'width':1920,'height':1080,'fps':30}

    def test_direction_filters_current_and_wrong_side(self):
        rows=[row(0),row(3),row(6),row(9)]
        self.assertEqual([r['frame'] for r in directional_records(rows,self.meta,6,'forward')],[0,3])
        back=directional_records(rows,self.meta,3,'backward')
        self.assertEqual([r['frame'] for r in back],[9,6])
        self.assertLess(back[0]['roll_degrees'],0)

    def test_prior_level_and_confidence_changes_invalidate_cache(self):
        history=[row(0)];key=context_key(history,self.meta,3,'forward',{})
        history[0]['level_confidence']=.2
        self.assertNotEqual(key,context_key(history,self.meta,3,'forward',{}))

    def test_bounded_context_keeps_full_history_and_reports_summary(self):
        with tempfile.TemporaryDirectory() as d:
            meta=dict(self.meta,cache=d);rows=[row(i*3) for i in range(50)]
            text,images,audit,_=build_context(rows,meta,150,'forward',{'history_char_budget':2000,'history_visual_frames':8,'recent_images':2},
                 lambda i:np.zeros((108,192,3),np.uint8))
            self.assertEqual(audit['history_count'],50)
            self.assertGreater(audit['summarized_record_count'],0)
            self.assertEqual(audit['recent_image_frames'],[144,147])
            self.assertEqual(audit['visual_frame_count'],10)
            self.assertEqual(audit['unsent_visual_frame_count'],40)
            self.assertTrue(Path(audit['history_file']).exists())
            self.assertIn('roll_degrees',text)

    def test_backward_history_contains_latest_accepted_result(self):
        rows=[dict(row(i),bbox=None,confidence=0,visibility='absent') for i in [0,3]]+[row(6),row(9)]
        calls=[]
        def attempt(current,seed,history):
            calls.append((current['frame'],[(r['frame'],r.get('analysis_source')) for r in history]))
            return dict(row(current['frame']),confidence=.8)
        result,_=backward_pass(rows,attempt,with_history=True)
        self.assertEqual(calls[0][1],[(9,None),(6,None)])
        self.assertEqual(calls[1][1],[(9,None),(6,None),(3,'backward')])

    def test_analysis_rate_validation_and_legacy_interval(self):
        c={'sample_interval':.5};self.assertEqual(set_analysis_fps(c),2)
        self.assertEqual(set_analysis_fps(c,10,29.97),10);self.assertAlmostEqual(c['sample_interval'],.1)
        for value in [0,-1,float('nan'),float('inf'),30]:
            with self.subTest(value=value),self.assertRaises(ValueError):set_analysis_fps({},value,29.97)


if __name__=='__main__':unittest.main()
