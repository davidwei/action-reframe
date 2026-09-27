import json,tempfile,unittest
from pathlib import Path
import cv2
import numpy as np
from box_verification import verify_box,confidence_from_verification

class BoxVerificationTests(unittest.TestCase):
    def test_exact_crop_blind_description_and_note_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ref=root/'reference.png';cv2.imwrite(str(ref),np.zeros((10,10,3),np.uint8))
            view=np.arange(100*200*3,dtype=np.uint8).reshape(100,200,3);calls=[]
            def api(url,payload):
                calls.append(payload);prompt=payload['messages'][0]['content'][-1]['text']
                if len(calls)==1:
                    self.assertNotIn('CLAIM_SENTINEL',prompt)
                    result={'box_description':'Only water','target_present':False,'target_complete':False,'confidence':.95,'reason':'No sailboat'}
                else:
                    self.assertIn('CLAIM_SENTINEL',prompt)
                    self.assertTrue(all(p['type']=='text' for p in payload['messages'][0]['content']))
                    result={'consistency':.05,'differences':['Sailboat claimed but only water seen'],'reason':'Contradiction'}
                return {'choices':[{'message':{'content':json.dumps(result)}}]}
            r=verify_box({'target':'boat','api_url':'http://test/v1'},view,[100,200,300,400],'CLAIM_SENTINEL boat', 'model',ref,root/'verify',api)
            self.assertNotIn('error',r);self.assertEqual(r['crop_pixels'],[20,20,60,40])
            np.testing.assert_array_equal(cv2.imread(r['crop_path']),view[20:40,20:60])
            self.assertEqual(confidence_from_verification(.9,r['description'],r['comparison']),0)
            verify_box({'target':'boat','api_url':'http://test/v1'},view,[100,200,300,400],'CLAIM_SENTINEL boat', 'model',ref,root/'verify',api)
            self.assertEqual(len(calls),2)

    def test_conservative_confidence_and_truncation(self):
        d={'target_present':True,'target_complete':True,'confidence':.95}
        self.assertEqual(confidence_from_verification(.8,d,{'consistency':.9}),.8)
        self.assertEqual(confidence_from_verification(.95,d,{'consistency':.2}),.2)
        d['target_complete']=False
        self.assertEqual(confidence_from_verification(.95,d,{'consistency':.9}),.64)

    def test_missing_note_and_verifier_failure_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            ref=Path(folder)/'reference.png';view=np.zeros((100,200,3),np.uint8);cv2.imwrite(str(ref),view)
            def fail(*args):raise RuntimeError('Unavailable')
            c={'target':'boat','api_url':'http://test/v1'}
            self.assertIn('error',verify_box(c,view,[100,100,200,200],None,'model',ref,folder,fail))
            self.assertIn('error',verify_box(c,view,[100,100,200,200],'boat','model',ref,folder,fail))
