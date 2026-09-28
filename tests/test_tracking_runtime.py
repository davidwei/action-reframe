import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from dual_tracking import observe_path,run_dual
from backward_tracking import bidirectional_pass


def good(frame):
    return dict(frame=frame,time=frame,bbox=[100,100,200,200],confidence=.9,visibility='visible')


def failed(frame):
    return dict(frame=frame,time=frame,bbox=None,confidence=0,visibility='uncertain',error='Invalid Qwen rectangle',error_kind='invalid_response')


class TrackingRuntimeTests(unittest.TestCase):
    def observe(self,responses,history=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        calls=[]
        def contextual(c,meta,index,direction,rows,model,images,prompt,tokens):
            calls.append(dict(prompt=prompt,history=rows,config=c))
            raw=responses[min(len(calls)-1,len(responses)-1)]
            return {'choices':[{'message':{'content':raw},'finish_reason':'stop'}]},{}
        result=observe_path({'target':'subject','verify_boxes':False},{'cache':str(root),'fps':1},{'frames':[{'roll':0}]},0,'model',history or [],'raw_angle','forward',
             (lambda *a:np.zeros((100,200,3),np.uint8),contextual,lambda path,value:Path(path).write_text(json.dumps(value))))
        return result,calls,root

    def test_replay_absence_format_failures_get_corrective_retry(self):
        # The two malformed shapes observed at frames 869, 899 and 929.
        for raw in ('{"bbox":[null,"confidence":0,"visibility":"absent"}',
                    '{"bbox":[null],"confidence":0,"visibility":"absent"}'):
            with self.subTest(raw=raw):
                result,calls,root=self.observe([raw,'{"bbox":null,"confidence":0,"visibility":"absent"}'])
                self.assertNotIn('error',result);self.assertIsNone(result['bbox'])
                self.assertEqual(result['visibility'],'absent');self.assertEqual(len(calls),2)
                self.assertIn('never [null]',calls[1]['prompt'])
                self.assertTrue(calls[0]['config']['_structured_tracking'])
                self.assertTrue(list(root.rglob('request_error.json')))
                self.assertEqual(result['temporal_context']['structured_response_attempts'],2)

    def test_persistent_schema_failure_is_reviewable_and_bounded(self):
        result,calls,_=self.observe(['{"bbox":[null],"confidence":0,"visibility":"absent"}'])
        self.assertEqual(len(calls),2)
        self.assertEqual(result['model_error']['kind'],'invalid_json_or_schema')
        self.assertIsNone(result['bbox'])
        self.assertTrue(Path(result['model_error']['response_file']).exists())

    def test_history_excludes_failed_detections_and_crop_errors(self):
        crop_failed=dict(good(-1),box_verification={'error':'bad crop response'})
        _,calls,_=self.observe(['{"bbox":null,"confidence":0,"visibility":"absent"}'],[good(-3),failed(-2),crop_failed])
        self.assertEqual([r['frame'] for r in calls[0]['history']],[-3])

    def test_dual_skips_three_bad_samples_and_preserves_good_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir();cv2.imwrite(str(cache/'reference.jpg'),np.zeros((10,10,3),np.uint8))
            c=dict(output_dir=str(root),video='unused',analysis_fps=1,backward_recovery=False)
            meta=dict(cache=str(cache),fps=1,samples=list(range(6)),frames=6)
            def observe(c,meta,gyro,index,model,history,path,direction,helpers):
                return failed(index) if index in (1,2,3) or (index==4 and path=='raw_angle') else good(index)
            save=lambda p,v:Path(p).write_text(json.dumps(v))
            with patch('dual_tracking.extract_gyro',return_value={'frames':[{'roll':0}]*6}),patch('manual_tracking.manual_observations',return_value={}),patch('dual_tracking.observe_path',side_effect=observe):
                result=run_dual(c,meta,'model',(None,None,save))
            self.assertEqual(len(result),6);self.assertEqual(result[4]['selected_path'],'leveled')
            self.assertEqual(result[5]['confidence'],.9)
            entries=json.loads((root/'analysis_failures.json').read_text())
            self.assertEqual([r['frame'] for r in entries],[1,2,3,4])
            self.assertEqual(len(entries[0]['failures']),2)
            self.assertEqual(json.loads((root/'analysis_progress.json').read_text())['stage'],'complete')

    def test_dual_does_not_hide_service_outage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir();(cache/'reference.jpg').write_bytes(b'fixture')
            row=dict(failed(0),model_error={'kind':'connection_error'},error='Server unreachable')
            with patch('dual_tracking.extract_gyro',return_value={'frames':[{'roll':0}]}),patch('manual_tracking.manual_observations',return_value={}),patch('dual_tracking.observe_path',return_value=row):
                with self.assertRaisesRegex(RuntimeError,'Server unreachable'):
                    run_dual(dict(output_dir=str(root),video='unused'),dict(cache=str(cache),samples=[0],fps=1),'model',(None,None,lambda p,v:None))

    def test_reverse_output_failure_keeps_last_successful_seed(self):
        calls=[]
        def attempt(current,seed,history):
            calls.append((current['frame'],seed['frame']))
            return failed(current['frame']) if current['frame']==2 else good(current['frame'])
        rows=[dict(good(i),confidence=0) for i in range(3)]+[good(3)]
        result,_=bidirectional_pass(rows,attempt,lambda *a:{'choice':'neither','confidence':0})
        self.assertEqual(calls,[(2,3),(1,3),(0,1)])
        self.assertEqual(result[1]['direction_choice'],'backward')
