import unittest
import numpy as np
from adaptive_verification import Schedule,settings
from zoom_path import minimum_crop_size,constrain_zoom,output_dimensions


class AdaptiveTests(unittest.TestCase):
    def config(self,**options):
        return dict(minimum_crop_short_side=180,analysis_fps=10,adaptive_verification=dict(mode='adaptive',**options))

    def motion(self,**kw):return dict(motion_quality=1.,feature_count=40,flow_error_px=.01,scale=1.,**kw)

    def test_tiny_threshold_is_short_side_and_linked_to_render_minimum(self):
        s=Schedule(self.config(),dict(frame=0,manual=True),'forward',30)
        a=s.decide(3,self.motion(),[0,0,89,200],[0,0])
        self.assertTrue(a['tiny']);self.assertFalse(a['proposed_verify']);self.assertEqual(a['reason'],'crop_too_small')
        self.assertFalse(s.decide(6,self.motion(),[0,0,90,90],[0,0])['tiny'])
        c=self.config();c['minimum_crop_short_side']=100
        s=Schedule(c,dict(frame=0,manual=True),'forward',30)
        self.assertFalse(s.decide(3,self.motion(),[0,0,60,100],[0,0])['tiny'])

    def test_timer_survives_checkpoint_and_backward_direction(self):
        for step in (1,-1):
            direction='forward' if step==1 else 'backward'
            s=Schedule(self.config(),dict(frame=30,manual=True),direction,30)
            a=s.decide(30+3*step,self.motion(),[0,0,120,120],[60,60]);self.assertFalse(a['proposed_verify'])
            seed=dict(frame=30+3*step,verification_schedule_state=s.snapshot())
            resumed=Schedule(self.config(),seed,direction,30)
            b=resumed.decide(30+15*step,self.motion(),[0,0,120,120],[60,60])
            self.assertTrue(b['proposed_verify']);self.assertEqual(b['last_pass_frame'],30)
            self.assertEqual(b['identity_age_seconds'],.5)

    def test_rejection_and_ambiguous_pass_keep_frequent_checks(self):
        s=Schedule(self.config(),dict(frame=0,manual=True),'forward',30)
        s.result(3,{},False)
        self.assertFalse(s.decide(4,self.motion(),[0,0,120,120],[60,60])['proposed_verify'])
        self.assertTrue(s.decide(6,self.motion(),[0,0,120,120],[60,60])['proposed_verify'])
        s.result(6,dict(description={'composition':'multiple_subjects'},comparison={'localization_support':'ambiguous'}),True)
        self.assertTrue(s.decide(9,self.motion(),[0,0,120,120],[60,60])['proposed_verify'])
        self.assertEqual(s.state['last_pass'],6)

    def test_render_portrait_square_and_rotation_conflict(self):
        for aspect,expected in [(16/9,(320,180)),(9/16,(180,320)),(4/3,(240,180)),(1,(180,180))]:
            np.testing.assert_allclose(minimum_crop_size(aspect),expected)
            extent,_,_,conflict=constrain_zoom([1],[[32,24]],[40],(64,48),(aspect*100,100),[0],180)
            self.assertGreaterEqual(extent[0],expected[1]);self.assertGreaterEqual(extent[0]*aspect,180-1e-8)
            self.assertTrue(conflict[0])
        self.assertEqual(output_dimensions(dict(output_width=1280,output_height=720),dict(width=1080,height=1920)),(720,1280))
        self.assertEqual(output_dimensions(dict(output_width=1280,output_height=720),dict(width=1000,height=1000)),(1280,1280))

    def test_invalid_settings(self):
        for opts in (dict(mode='bad'),dict(tiny_box_ratio=2),dict(stable_seconds=0)):
            with self.assertRaises(ValueError):settings(dict(adaptive_verification=opts))
