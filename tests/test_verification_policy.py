"""Behavioral cases: partial targets, broad crops, exclusions, anchors and progress."""
import copy
import tempfile
import unittest
from verification_policy import accepted_row, anchor_eligible, verification_decision, target_description
from tracking_selection import TrackSelector
from tracking_progress import TrackingProgress
from analysis_scheduler import AnchorScheduler


def evidence(score=.9, present=True, localization='supported', exclusion='pass', visibility='boundary_cut'):
    return dict(version=7, description=dict(box_description='Visible object',composition='isolated_subject',visibility=visibility),
                comparison=dict(match_score=score,target_present=present,target_complete=visibility=='whole',
                    localization_support=localization,localization_reason='Crop evidence',exclusion_check=exclusion,exclusion_reason='Identity evidence'))


def row(result=None, **kwargs):
    result=result or evidence()
    return dict(frame=0,time=0,bbox=[100,100,200,200],confidence=result['comparison']['match_score'],
                visibility='partial',localized=True,box_verification=result,**kwargs)


class VerificationPolicyTests(unittest.TestCase):
    def test_representative_identity_and_localization_cases(self):
        cases=[('whole',evidence(visibility='whole'),'accepted'),
               ('partial',evidence(),'accepted'),
               ('blurred',evidence(.85,visibility='unclear'),'accepted'),
               ('wrong_subject_same_color',evidence(.95,exclusion='contradicted'),'identity_rejected'),
               ('whole_scene_matching_features',evidence(.95,localization='ambiguous'),'localization_rejected'),
               ('water_only',evidence(0,present=False,localization='unsupported'),'identity_rejected')]
        for name,result,expected in cases:
            with self.subTest(name=name):
                self.assertEqual(verification_decision(result)['category'],expected)
                self.assertEqual(accepted_row(row(result)),expected=='accepted')

    def test_partial_can_anchor_but_unknown_exclusion_and_flow_cannot(self):
        self.assertTrue(anchor_eligible(row()))
        uncertain=row(evidence(exclusion='unclear'))
        self.assertTrue(accepted_row(uncertain));self.assertFalse(anchor_eligible(uncertain))
        flow=row();flow['localized']=False
        self.assertTrue(accepted_row(flow));self.assertFalse(anchor_eligible(flow))
        scheduler=AnchorScheduler([0,1],[0,1],[],None,None,lambda state:None)
        self.assertTrue(scheduler.can_anchor(row()))
        self.assertFalse(scheduler.can_anchor(uncertain))

    def test_human_override_and_invalid_coordinates(self):
        wrong=row(evidence(.99,exclusion='contradicted'),manual=True)
        self.assertTrue(accepted_row(wrong));self.assertTrue(anchor_eligible(wrong))
        for bbox in (None,[100,100,50,50],[0,0,1001,100],[],[0,0,float('nan'),1]):
            self.assertFalse(accepted_row(dict(row(),bbox=bbox)))
        self.assertFalse(accepted_row(dict(row(),conflict=True)))

    def test_selection_rejects_high_score_wrong_box(self):
        bad=row(evidence(.99,localization='ambiguous'))
        good=row(evidence(.85))
        chosen=TrackSelector().choose(bad,good,lambda *a:self.fail('No adjudication needed'))
        self.assertEqual(chosen['selected_path'],'leveled')
        both=TrackSelector().choose(bad,bad,lambda *a:self.fail('No accepted candidates'))
        self.assertIsNone(both['bbox'])
        self.assertEqual(bad['confidence'],.99) # Diagnostic identity score is retained.

    def test_progress_reasons_thresholds_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            p=TrackingProgress(directory,'v7',range(4),range(4),0,3,.5,anchor_threshold=.85)
            for i,result in enumerate([evidence(),evidence(localization='ambiguous'),evidence(exclusion='contradicted'),{'version':7,'error':'truncated'}]):
                p.verification(i,result,'raw')
            result=p.publish({})['verification']
            self.assertEqual((result['accepted'],result['rejected'],result['errored']),(1,2,1))
            self.assertEqual(result['confidence']['passed'],1);self.assertEqual(result['confidence']['high'],1)
            self.assertEqual(result['rejection_reasons'],dict(identity_rejected=1,localization_rejected=1,request_error=1,unclassified=0))
            resumed=TrackingProgress(directory,'v7',range(4),range(4),0,3,.5,anchor_threshold=.85,resuming=True)
            self.assertEqual(resumed.publish({})['verification'],result)
            resumed.verification(1,evidence(),'leveled')
            self.assertEqual(resumed.publish({})['verification']['rejection_reasons']['localization_rejected'],0)

    def test_approved_identity_does_not_mutate_original(self):
        config=dict(target='Original instruction',approved_target_description='Reviewed identity')
        before=copy.deepcopy(config)
        self.assertEqual(target_description(config),'Reviewed identity');self.assertEqual(config,before)
        self.assertEqual(target_description({'target':'Original instruction'}),'Original instruction')

    def test_new_incomplete_schema_and_errors_fail_closed(self):
        result=evidence();del result['comparison']['localization_support']
        self.assertFalse(verification_decision(result)['accepted'])
        self.assertEqual(verification_decision(dict(result,error='Model failed'))['category'],'request_error')
        self.assertFalse(accepted_row(row(evidence(.49))))
        self.assertFalse(anchor_eligible(row(evidence(.84))))
