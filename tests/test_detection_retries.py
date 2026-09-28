import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import cv2
from dual_tracking import observe_path
from temporal_context import build_context


class DetectionRetryTests(unittest.TestCase):
    def test_manual_crop_and_no_coordinates_in_detection_history(self):
        with tempfile.TemporaryDirectory() as folder:
            image=np.arange(100*200*3,dtype=np.uint8).reshape(100,200,3)
            history=[dict(frame=0,bbox=[100,200,300,600],confidence=1,visibility='visible',manual=True,note='old box [100,200,300,600]')]
            text,images,audit,_=build_context(history,{'cache':folder,'fps':30},1,'forward',{'omit_box_coordinates':True},lambda _:image)
            records=json.loads(text.split('\n',1)[1])['individual_frame_records']
            self.assertNotIn('bbox',records[0]);self.assertNotIn('note',records[0])
            self.assertEqual(audit['manual_crop_frames'],[0])
            crop=next(i for i in images if i.get('kind')=='human_target_crop')
            np.testing.assert_array_equal(cv2.imread(crop['path']),image[20:60,20:60])
            self.assertEqual(audit['visual_frame_count'],1)
            self.assertEqual(audit['attached_image_count'],2)

    def run_case(self,success_at=None,direction='forward'):
        with tempfile.TemporaryDirectory() as folder:
            requests=[];verifications=[];progress=[]
            def completion(c,meta,index,direction,history,model,images,prompt,tokens):
                self.assertTrue(c['temporal_context']['omit_box_coordinates'])
                self.assertIn('APPROVED_IDENTITY',prompt);self.assertNotIn('OLD_TARGET',prompt)
                requests.append((images,prompt,meta['cache']))
                return {'choices':[{'message':{'content':json.dumps(dict(bbox=[100,200,300,600],confidence=.9,visibility='visible',box_note='boat'))}}]},{}
            def verify(*args):
                verifications.append(1);good=len(verifications)==success_at
                return dict(version=7,crop_path=str(Path(folder)/'crop.png'),description=dict(target_present=good,target_complete=good,confidence=.9 if good else .2,box_description='boat' if good else 'water'),comparison=dict(match_score=.9 if good else 0,target_present=good,target_complete=False,exclusion_check='pass',exclusion_reason='No contradiction',localization_support='supported' if good else 'unsupported',localization_reason='Visible crop evidence'))
            c={'target':'OLD_TARGET','approved_target_description':'APPROVED_IDENTITY','verify_boxes':True}
            with patch('box_verification.verify_box',side_effect=verify):
                result=observe_path(c,{'cache':folder,'fps':30}, {'frames':[{'roll':10}]},0,'test',[],'leveled',direction,
                    (lambda *args:np.zeros((100,200,3),np.uint8),completion,lambda *args:None),verification_callback=progress.append)
            self.assertEqual(len(progress),len(verifications))
            return result,requests

    def test_retry_corrects_rejected_proposal_and_stops(self):
        result,requests=self.run_case(2)
        self.assertEqual(result['confidence'],.9)
        self.assertEqual(result['verification_retry_count'],1)
        self.assertEqual(len(requests[0][0]),2);self.assertEqual(len(requests[1][0]),3)
        self.assertIn('water',requests[1][1]);self.assertIn('NOT an identity reference',requests[1][1])
        self.assertNotEqual(requests[0][2],requests[1][2])
        self.assertEqual(len(result['detection_attempts']),2)

    def test_partial_target_stops_without_completeness_retry(self):
        result,requests=self.run_case(1)
        self.assertEqual(len(requests),1)
        self.assertFalse(result['box_verification']['comparison']['target_complete'])
        self.assertEqual(result['confidence'],.9)

    def test_backward_exhaustion_is_bounded_and_uncertain(self):
        result,requests=self.run_case(direction='backward')
        self.assertEqual(len(requests),3)
        self.assertEqual(result['confidence'],0)
        self.assertEqual(result['verification_retry_count'],2)
        self.assertEqual(result['direction'],'backward')
