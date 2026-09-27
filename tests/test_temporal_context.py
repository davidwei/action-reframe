import tempfile
import unittest
from pathlib import Path
import numpy as np
from temporal_context import directional_records, context_key, build_context, select_history
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

    def test_selected_images_deduplicate_and_keep_full_history_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            meta=dict(self.meta,cache=d,user_reference_frames=[0,0,180])
            rows=[row(i*3) for i in range(50)]
            for r in rows[20:30]:r['confidence']=.7
            text,images,audit,_=build_context(rows,meta,150,'forward',{},
                lambda i:np.zeros((108,192,3),np.uint8))
            self.assertEqual(audit['history_count'],50)
            self.assertEqual(audit['recent_image_frames'],[135,138,141,144,147])
            self.assertEqual(audit['image_groups']['moderate_or_high_added'],[])
            self.assertEqual(audit['image_groups']['high_added'],[])
            self.assertEqual(audit['visual_frame_count'],7)
            self.assertEqual(audit['individual_record_count'],5)
            self.assertEqual(audit['summarized_record_count'],0)
            self.assertEqual(audit['unsent_visual_frame_count'],44)
            self.assertEqual(audit['user_reference_frames'],[0,180])
            self.assertTrue(Path(audit['history_file']).exists())
            self.assertIn('roll_degrees',text)
            self.assertIn('USER-SELECTED',images[0]['label'])
            _,_,compressed,_=build_context(rows,meta,150,'forward',{},lambda i:np.zeros((108,192,3),np.uint8),2)
            self.assertEqual(compressed['selected_image_frames'],audit['selected_image_frames'])
            self.assertLess(compressed['image_width'],audit['image_width'])

    def test_confidence_bands_and_backward_traversal(self):
        rows=[dict(row(i),confidence=score) for i,score in enumerate([.64,.65,.84,.85,.99,.9])]
        rows[-1]['bbox']=None
        records=directional_records(rows,self.meta,-1,'backward')
        selected,groups=select_history(records,{'recent_images':3})
        self.assertEqual(groups['recent'],[2,1,0])
        self.assertEqual(groups['moderate_or_high_added'],[3,4])
        self.assertEqual(groups['high_added'],[])
        self.assertEqual(len(selected),5)
        self.assertEqual(select_history([],{}),([] ,{'recent':[],'moderate_or_high_added':[],'high_added':[]}))

    def test_quota_topups_best_and_worst_case(self):
        rows=[dict(row(i),confidence=.9 if i<5 else .7 if i<10 else .1) for i in range(15)]
        selected,groups=select_history(rows,{})
        self.assertEqual(len(selected),15)
        self.assertEqual(groups['recent'],[10,11,12,13,14])
        self.assertEqual(groups['moderate_or_high_added'],[9,8,7,6,5])
        self.assertEqual(groups['high_added'],[4,3,2,1,0])
        for r in rows:r['confidence']=.9
        selected,groups=select_history(rows,{})
        self.assertEqual(len(selected),5)
        self.assertEqual(groups['moderate_or_high_added'],[])
        self.assertEqual(groups['high_added'],[])
        # High-confidence frames already in the moderate-or-high top-up count twice.
        for r in rows[10:]:r['confidence']=.1
        selected,groups=select_history(rows,{})
        self.assertEqual(len(selected),10)
        self.assertEqual(groups['high_added'],[])
        for r in rows:r['confidence']=.1
        selected,groups=select_history(rows,{})
        self.assertEqual([r['frame'] for r in selected],[10,11,12,13,14])
        self.assertEqual(groups['moderate_or_high_added'],[])
        self.assertEqual(groups['high_added'],[])

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
