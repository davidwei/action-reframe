import json,tempfile,unittest
from pathlib import Path
import cv2
import numpy as np
from box_verification import verify_box,confidence_from_verification

class BoxVerificationTests(unittest.TestCase):
    def test_exact_crop_blind_description_and_text_only_matching(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ref=root/'reference.png';cv2.imwrite(str(ref),np.zeros((10,10,3),np.uint8))
            view=np.arange(100*200*3,dtype=np.uint8).reshape(100,200,3);calls=[]
            def api(url,payload):
                calls.append(payload);content=payload['messages'][0]['content'];prompt=content[-1]['text']
                self.assertEqual(len(payload['messages']),1)
                if 'human-selected crop' in prompt:
                    result={'target_description':'TRUSTED_SENTINEL green triangular sailboat'}
                elif 'Describe only what' in prompt:
                    self.assertNotIn('CLAIM_SENTINEL',prompt);self.assertNotIn('TARGET_SENTINEL',prompt);self.assertNotIn('TRUSTED_SENTINEL',prompt)
                    self.assertEqual(sum(p['type']=='image_url' for p in content),1)
                    result={'box_description':'Only water'}
                else:
                    self.assertNotIn('CLAIM_SENTINEL',prompt);self.assertNotIn('TARGET_SENTINEL',prompt)
                    self.assertIn('TRUSTED_SENTINEL',prompt);self.assertIn('Only water',prompt)
                    self.assertTrue(all(p['type']=='text' for p in content))
                    result={'match_score':.05,'target_present':False,'target_complete':False,'differences':['Only water seen'],'reason':'Wrong content'}
                return {'choices':[{'message':{'content':json.dumps(result)}}]}
            c={'target':'TARGET_SENTINEL','api_url':'http://test/v1'}
            r=verify_box(c,view,[100,200,300,400],'CLAIM_SENTINEL', 'model',ref,root/'verify',api)
            self.assertNotIn('error',r);self.assertEqual(r['crop_pixels'],[20,20,60,40])
            np.testing.assert_array_equal(cv2.imread(r['crop_path']),view[20:40,20:60])
            self.assertEqual(confidence_from_verification(.9,r['description'],r['comparison']),0)
            verify_box(c,view,[100,200,300,400],'CLAIM_SENTINEL', 'model',ref,root/'verify',api)
            self.assertEqual(len(calls),3)
            # A different proposal reuses the trusted descriptor; missing note is fine.
            r=verify_box(c,view,[200,200,400,400],None,'model',ref,root/'verify',api)
            self.assertNotIn('error',r);self.assertEqual(len(calls),5)

    def test_human_approved_description_bypasses_reference_model_and_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            ref=Path(folder)/'reference.png';view=np.zeros((100,200,3),np.uint8);cv2.imwrite(str(ref),view)
            calls=[]
            def api(url,payload):
                prompt=payload['messages'][0]['content'][-1]['text'];calls.append(prompt)
                if 'Describe only' in prompt:result={'box_description':'A green sail'}
                else:
                    self.assertIn('APPROVED',prompt)
                    result={'match_score':.9,'target_present':True,'target_complete':True,'differences':[],'reason':'match'}
                return {'choices':[{'message':{'content':json.dumps(result)}}]}
            c={'target':'boat','api_url':'http://test/v1','approved_target_description':'APPROVED green sail'}
            r=verify_box(c,view,[100,100,400,500],None,'model',ref,folder,api)
            self.assertNotIn('error',r);self.assertEqual(len(calls),2)
            self.assertEqual(r['reference_description']['source'],'human_approved')
            c['approved_target_description']='APPROVED green sail and hull'
            verify_box(c,view,[100,100,400,500],None,'model',ref,folder,api)
            self.assertEqual(len(calls),4)

    def test_score_ignores_proposal_confidence_and_separates_completeness(self):
        d={'box_description':'A green sail with clipped tip'}
        comparison={'match_score':.9,'target_present':True,'target_complete':False}
        self.assertEqual(confidence_from_verification(.1,d,comparison),.9)
        self.assertEqual(confidence_from_verification(1,d,comparison),.9)
        comparison['target_present']=False
        self.assertEqual(confidence_from_verification(1,d,comparison),0)
        for bad in [float('nan'),True,1.1,-.1]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                confidence_from_verification(1,d,dict(comparison,match_score=bad))

    def test_verifier_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            ref=Path(folder)/'reference.png';view=np.zeros((100,200,3),np.uint8);cv2.imwrite(str(ref),view)
            def fail(*args):raise RuntimeError('Unavailable')
            c={'target':'boat','api_url':'http://test/v1'}
            self.assertIn('error',verify_box(c,view,[100,100,200,200],None,'model',ref,folder,fail))
