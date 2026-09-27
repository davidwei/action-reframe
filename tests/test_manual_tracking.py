import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dual_tracking import run_dual
from reframe import analyze
from temporal_context import directional_records, select_history


class ManualTrackingTests(unittest.TestCase):
    def test_dual_manual_off_grid_skips_both_directions_and_anchors_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'reference.jpg').write_bytes(b'reference')
            (root/'corrections.json').write_text(json.dumps({'7':{'bbox':[100,20,160,80]}}))
            c={'output_dir':folder,'video':'test','analysis_fps':2,'backward_recovery':True}
            meta={'cache':folder,'samples':[0,15,30],'fps':30,'width':200,'height':100,'frames':31}
            calls=[]
            def observe(c,meta,gyro,index,model,history,path,direction,helpers):
                self.assertNotEqual(index,7)
                calls.append((index,path,direction,history))
                return dict(frame=index,time=index/30,path=path,direction=direction,bbox=[500,200,800,800],confidence=.9,visibility='visible')
            def save(path,value):Path(path).write_text(json.dumps(value))
            with patch('dual_tracking.extract_gyro',return_value={'frames':[{'roll':0}]*31}),patch('dual_tracking.observe_path',side_effect=observe),patch('dual_tracking.adjudicate_pair',side_effect=AssertionError('No adjudication expected')):
                rows=run_dual(c,meta,'test',(None,None,save))
            anchor=next(r for r in rows if r['frame']==7)
            self.assertEqual(anchor['selected_path'],'manual')
            self.assertEqual(anchor['confidence'],1)
            self.assertEqual(anchor['bbox'],[500,200,800,800])
            for path in ('raw_angle','leveled'):
                for index,direction in [(15,'forward'),(0,'backward')]:
                    history=next(h for i,p,d,h in calls if (i,p,d)==(index,path,direction))
                    self.assertTrue(any(r['frame']==7 and r['manual'] for r in history))
                reverse=next(h for i,p,d,h in calls if (i,p,d)==(0,path,'backward'))
                self.assertEqual([r['frame'] for r in reverse],[30,15,7])

    def test_single_manual_off_grid_skips_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'corrections.json').write_text('{"7":{"bbox":[10,20,30,40]}}')
            c={'output_dir':folder,'api_url':'unused','analysis_fps':2,'backward_recovery':False}
            meta={'samples':[0,15],'fps':30,'width':100,'height':100,'frames':16}
            calls=[]
            def observe(c,meta,index,model,history):
                calls.append((index,list(history)))
                return dict(frame=index,time=index/30,bbox=None,confidence=0)
            with patch('reframe.prepare',return_value=meta),patch('reframe.api',return_value={'data':[{'id':'test'}]}),patch('reframe.observe',side_effect=observe):
                rows=analyze(c)
            self.assertEqual([i for i,h in calls],[0,15])
            self.assertTrue(calls[1][1][-1]['manual'])
            self.assertEqual(rows[1]['confidence_source'],'human')

    def test_manual_context_fills_quota_in_either_direction_without_duplicates(self):
        for direction in ('forward','backward'):
            frames=list(range(10)) if direction=='forward' else list(range(20,10,-1))
            rows=[dict(frame=f,bbox=[1,1,2,2],confidence=1 if i<5 else .2,manual=i<5,visibility='visible') for i,f in enumerate(frames)]
            records=directional_records(rows,{'fps':30},10,direction)
            selected,groups=select_history(records,{})
            self.assertEqual(len(selected),10)
            self.assertEqual(sum(r['source']=='manual' for r in selected),5)
            self.assertEqual(len({r['frame'] for r in selected}),10)
            self.assertEqual(groups['high_added'],[])
