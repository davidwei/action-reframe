import copy
import unittest
from backward_tracking import backward_pass, confident


def row(frame, score=0, box=None, **extra):
    return dict(frame=frame,time=frame/30,confidence=score,bbox=box,
                visibility='visible' if box else 'absent',shoreline=[0,300,1000,400],**extra)


GOOD={'bbox':[100,100,200,300],'confidence':.8,'visibility':'visible','note':'same target'}


class BackwardTests(unittest.TestCase):
    def test_extends_multiple_gaps_without_touching_good_or_trailing_frames(self):
        source=[row(0),row(15),row(30,.9,GOOD['bbox']),row(45),row(60,.95,GOOD['bbox']),row(75)]
        original=copy.deepcopy(source);calls=[]
        def attempt(current,seed):
            calls.append((current['frame'],seed['frame']));return copy.deepcopy(GOOD)
        result,report=backward_pass(source,attempt)
        self.assertEqual(calls,[(15,30),(0,15),(45,60)])
        self.assertEqual(source,original)
        self.assertEqual(result[2],source[2]);self.assertEqual(result[4],source[4]);self.assertEqual(result[5],source[5])
        self.assertEqual(report['recovered_samples'],3)
        self.assertEqual(result[0]['first_pass_tracking']['confidence'],0)
        self.assertEqual(result[0]['shoreline'],source[0]['shoreline'])

    def test_stops_at_failed_step_without_bridging_occlusion(self):
        source=[row(0),row(15),row(30),row(45,.9,GOOD['bbox'])];calls=[]
        def attempt(current,seed):
            calls.append(current['frame'])
            return copy.deepcopy(GOOD) if current['frame']==30 else dict(GOOD,confidence=.4)
        result,report=backward_pass(source,attempt)
        self.assertEqual(calls,[30,15]);self.assertEqual(report['recovered_samples'],1)
        self.assertFalse(result[1]['backward_attempt']['accepted']);self.assertFalse(confident(result[1]))
        self.assertEqual(result[0],source[0])

    def test_no_anchor_no_attempts(self):
        source=[row(0),row(15)]
        result,report=backward_pass(source,lambda *_:self.fail('no end anchor'))
        self.assertEqual(result,source);self.assertEqual(report['attempted_samples'],0)

    def test_manual_absence_blocks_chain(self):
        source=[row(0),row(15,manual=True),row(30),row(45,.9,GOOD['bbox'])]
        result,report=backward_pass(source,lambda *_:copy.deepcopy(GOOD))
        self.assertEqual(report['recovered_samples'],1);self.assertEqual(result[1],source[1])

    def test_scene_cut_and_invalid_model_values_are_rejected(self):
        for evidence in [dict(GOOD,scene_cut=True),dict(GOOD,bbox=[200,100,100,300]),
                         dict(GOOD,confidence=float('nan')),dict(GOOD,error='server failure')]:
            with self.subTest(evidence=evidence):
                result,report=backward_pass([row(0),row(15,.9,GOOD['bbox'])],lambda *_:evidence)
                self.assertEqual(report['recovered_samples'],0);self.assertFalse(confident(result[0]))


if __name__=='__main__':unittest.main()
