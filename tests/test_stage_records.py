import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import cv2
import numpy as np
from stage_records import Store, configure, summary
from box_verification import verify_box
from visual_tracking import VisualTracker

class StageRecordsTests(unittest.TestCase):
    def test_atomic_deduplication_and_failure_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder,Path(folder)/'usage.jsonl');calls=[]
            def compute(path):calls.append(1);return {'answer':42}
            with ThreadPoolExecutor(4) as pool:
                rows=list(pool.map(lambda _:store.run('test',1,{'input':1},compute),range(8)))
            self.assertEqual(len(calls),1)
            record=Path(rows[0][1]['record']);original=record.read_bytes()
            store.run('test',1,{'input':1},compute)
            self.assertEqual(record.read_bytes(),original)
            store.run('test',2,{'input':1},compute)
            self.assertEqual(len(calls),2)
            with self.assertRaises(RuntimeError):store.run('failure',1,{},lambda _:(_ for _ in ()).throw(RuntimeError('failed')))
            self.assertEqual(store.run('failure',1,{},compute)[0]['answer'],42)
            self.assertEqual(summary(Path(folder)/'usage.jsonl')['test'],dict(computed=2,reused=8))

    def test_cross_run_verification_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=np.zeros((40,40,3),np.uint8)
            ref=root/'ref.png';cv2.imwrite(str(ref),image);calls=[]
            def api(url,payload):
                prompt=payload['messages'][0]['content'][-1]['text'];calls.append(prompt)
                if 'Describe only' in prompt:
                    result=dict(box_description='Green boat',viewpoint='external_view',composition='isolated_subject',visibility='whole')
                else:result=dict(match_score=.7,target_present=True,target_complete=True,exclusion_check='pass',exclusion_reason='',localization_support='supported',localization_reason='',differences=[],reason='Matches')
                return {'choices':[{'message':{'content':json.dumps(result)}}]}
            def run(number,description,threshold,model='test'):
                c=dict(output_dir=str(root/str(number)),stage_store_dir=str(root/'shared'),api_url='http://test/v1',approved_target_description=description,tracking_selection=dict(confidence_threshold=threshold))
                configure(c)
                return verify_box(c,image,[0,0,1000,1000],None,model,ref,root/str(number)/'verify',api)
            first=run(1,'Green boat',.5);self.assertEqual(len(calls),2)
            second=run(2,'Green boat',.8);self.assertEqual(len(calls),2)
            self.assertTrue(first['decision']['accepted']);self.assertFalse(second['decision']['accepted'])
            run(3,'Green boat with white sail',.5);self.assertEqual(len(calls),3)
            run(4,'Green boat with white sail',.5,'new-model');self.assertEqual(len(calls),5)

    def test_optical_cached_state_continues_identically(self):
        with tempfile.TemporaryDirectory() as folder:
            rng=np.random.default_rng(42);image=rng.integers(0,255,(100,100,3),dtype=np.uint8)
            images=[np.roll(image,i,axis=1) for i in range(3)]
            store=Store(folder)
            first=VisualTracker(store).initialize(images[0],[10,10,80,80])
            expected=[first.update(frame) for frame in images[1:]]
            self.assertTrue(all(row['reliable'] for row in expected))
            second=VisualTracker(store).initialize(images[0],[10,10,80,80])
            with patch.object(second,'_update',side_effect=AssertionError('Should reuse')):
                actual=[second.update(frame) for frame in images[1:]]
            for a,b in zip(actual,expected):
                self.assertEqual(a['box'],b['box']);self.assertTrue(a['stage_record']['reused'])
            np.testing.assert_array_equal(first.points,second.points)

    def test_discovery_uses_actual_images_and_prompt_not_output_paths(self):
        from reframe import contextual_completion
        from tracking_response import validate_detection
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'image.png';cv2.imwrite(str(image),np.zeros((10,10,3),np.uint8))
            calls=[]
            def api(url,payload):
                if url.endswith('/tokenize'):return {'count':10}
                calls.append(payload)
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(dict(bbox=[1,2,30,40],confidence=.8,visibility='visible'))}}]}
            c=dict(output_dir=str(root/'run1'),stage_store_dir=str(root/'shared'),api_url='http://test/v1',_structured_tracking=True,_stage_validator=validate_detection)
            meta=dict(frames=2,cache=str(root));args=(meta,0,'forward',[],'model',[image],'Find boat',1000)
            with patch('reframe.api',side_effect=api),patch('reframe.build_context',return_value=('history',[],{},root)):
                contextual_completion(c,*args)
                contextual_completion(dict(c,output_dir=str(root/'run2')),*args)
                self.assertEqual(len(calls),1)
                cv2.imwrite(str(image),np.ones((10,10,3),np.uint8))
                contextual_completion(c,*args);self.assertEqual(len(calls),2)
                contextual_completion(c,*args[:-2],'Find skier',1000);self.assertEqual(len(calls),3)
