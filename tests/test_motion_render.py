import tempfile
import unittest
import numpy as np
from pathlib import Path
from optical_diagnostics import record
from motion_render import merge_motion,motion_usable
from verification_policy import verification_decision,accepted_row,anchor_eligible
from zoom_path import confident_frames
from analysis_scheduler import AnchorScheduler


def verification(localization='ambiguous',exclusion='pass',score=.9,motion=True):
    return dict(version=7,verification_context='optical_motion' if motion else 'independent',motion_reliable=motion,
        comparison=dict(target_present=True,match_score=score,localization_support=localization,exclusion_check=exclusion,target_complete=False))


def motion(frame):
    return dict(frame=frame,time=frame,bbox=[100,100,200,200],confidence=0,visibility='visible',motion_reliable=True,
        analysis_source='optical_unverified',identity_verified=False,localized=False)


class MotionRenderTests(unittest.TestCase):
    def test_relaxation_requires_reliable_motion_identity_and_threshold(self):
        self.assertTrue(verification_decision(verification())['accepted'])
        self.assertFalse(verification_decision(verification(motion=False))['accepted'])
        self.assertFalse(verification_decision(verification(localization='unsupported'))['accepted'])
        self.assertFalse(verification_decision(verification(exclusion='contradicted'))['accepted'])
        self.assertFalse(verification_decision(verification(score=.49))['accepted'])
        r=dict(motion(1),confidence=.9,identity_verified=True,analysis_source='flow_crop_validation',box_verification=verification())
        self.assertTrue(accepted_row(r));self.assertFalse(anchor_eligible(r))
        self.assertFalse(anchor_eligible(dict(r,localized=True)))

    def test_unverified_motion_continues_without_becoming_anchor_or_suppressing_discovery(self):
        seed=dict(motion(0),confidence=1,manual=True,identity_verified=True,localized=True)
        visits=[];discovery=[]
        def propagate(source,index,step,rows):visits.append(index);return motion(index)
        def discover(index,rows):discovery.append(index);return dict(frame=index,time=index,bbox=None,confidence=0,visibility='absent')
        s=AnchorScheduler(range(4),range(4),[seed],propagate,discover,lambda state:None)
        s.run()
        self.assertEqual(visits,[1,2,3]);self.assertEqual(s.state['anchors'],[0])
        self.assertEqual(discovery,[1,2,3])
        self.assertFalse(accepted_row(motion(1),0))

    def test_motion_drives_zoom_but_human_labels_and_failed_motion_take_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            meta=dict(width=200,height=100,frames=6,fps=30)
            for i in range(1,5):record(folder,dict(frame=i,reliable=True,bbox_px=[20,10,60,50]))
            record(folder,dict(frame=4,reliable=False,bbox_px=None))
            human=dict(frame=2,bbox=None,confidence=0,visibility='absent',manual=True)
            trusted=dict(frame=3,bbox=[500,500,700,700],confidence=.9,visibility='visible')
            rows=merge_motion([human,trusted],meta,folder,.5)
            byframe={r['frame']:r for r in rows}
            self.assertEqual(byframe[1]['bbox'],[100,100,300,500])
            self.assertTrue(motion_usable(byframe[1]));self.assertFalse(accepted_row(byframe[1]))
            self.assertIsNone(byframe[2]['bbox']);self.assertEqual(byframe[3]['bbox'],trusted['bbox'])
            self.assertNotIn(4,byframe)
            np.testing.assert_array_equal(confident_frames(rows,{},6,.5),[1,3])
            np.testing.assert_array_equal(confident_frames(rows,{'1':{'bbox':None}},6,.5),[3])

    def test_historical_checkpoint_is_used_without_inventing_intermediate_boxes(self):
        rows=[dict(frame=3,time=.1,bbox=None,confidence=0,visibility='uncertain',propagation_validation={
            'raw_angle':dict(analysis_source='flow_crop_validation',bbox=[100,100,300,500],confidence=0)})]
        with tempfile.TemporaryDirectory() as folder:
            result=merge_motion(rows,dict(width=200,height=100,frames=5,fps=30),folder,.5)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['frame'],3)
        self.assertTrue(motion_usable(result[0]));self.assertEqual(result[0]['confidence'],0)
