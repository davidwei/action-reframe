import copy
import unittest
import cv2
import numpy as np
from analysis_scheduler import AnchorScheduler
from visual_tracking import VisualTracker,relaxed_box,too_large
from tracking_evidence import resolve


def row(frame,score=.9,manual=False,localized=True):
    return dict(frame=frame,time=frame/2,bbox=[100,100,200,200],confidence=score,visibility='visible',manual=manual,
                localized=localized,box_verification={'comparison':{'target_complete':True}})


class SchedulerTests(unittest.TestCase):
    def test_bidirectional_then_discovery_restart_and_resume(self):
        saved=[];calls=[]
        def propagate(source,index,step,rows):
            calls.append(('propagate',source['frame'],index))
            return row(index,score=.9 if index in (1,3,5) else 0,localized=False)
        def discover(index,rows):calls.append(('discover',index));return row(index,.95 if index==6 else 0)
        scheduler=AnchorScheduler(range(7),range(7),[row(2,1,True)],propagate,discover,lambda s:saved.append(copy.deepcopy(s)))
        scheduler.run()
        self.assertEqual(calls[0],('propagate',2,1));self.assertEqual(calls[1],('propagate',2,3))
        self.assertIn(('discover',0),calls);self.assertIn(('discover',6),calls)
        self.assertIn(('propagate',6,5),calls)
        self.assertEqual(saved[-1]['stage'],'complete')
        before=len(calls)
        AnchorScheduler(range(7),range(7),[],propagate,discover,lambda s:None,checkpoint=saved[-1]).run()
        self.assertEqual(len(calls),before)
        self.assertNotIn(1,saved[-1]['anchors']) # verified propagation isn't a localized anchor

    def test_manual_absence_and_conflicting_branches(self):
        human=row(2,1,True);absent=dict(row(3,0,True),bbox=None,visibility='absent')
        calls=[]
        state=[]
        AnchorScheduler(range(5),range(5),[human,absent],lambda s,i,d,r:(calls.append(i) or row(i)),lambda i,r:row(i,0),lambda s:state.append(copy.deepcopy(s))).run()
        self.assertNotIn(3,calls);self.assertIsNone(state[-1]['results']['3']['bbox'])
        other=dict(row(2),bbox=[500,500,600,600])
        chosen,conflict=resolve(row(2),other)
        self.assertTrue(conflict);self.assertIsNone(chosen['bbox'])
        chosen,conflict=resolve(human,other);self.assertEqual(chosen,human);self.assertFalse(conflict)

    def test_high_score_incomplete_box_is_not_anchor(self):
        s=AnchorScheduler([0,1],[0,1],[],None,None,lambda s:None)
        candidate=row(0,.99);candidate['box_verification']['comparison']['target_complete']=False
        self.assertFalse(s.can_anchor(candidate))

    def test_failure_keeps_pending_work_for_resume(self):
        states=[]
        s=AnchorScheduler([0,1],[0,1],[row(0,1,True)],lambda *a:{'error':'API down'},None,lambda s:states.append(copy.deepcopy(s)))
        with self.assertRaises(RuntimeError):s.run()
        self.assertEqual(states[-1]['queue'][0]['target'],1)
        self.assertEqual(states[-1]['attempts'],{})


class FlowTests(unittest.TestCase):
    def test_translation_forward_and_backward(self):
        rng=np.random.default_rng(1);image=np.zeros((160,200,3),np.uint8)
        image[40:100,60:120]=rng.integers(0,255,(60,60,3),dtype=np.uint8)
        moved=cv2.warpAffine(image,np.float32([[1,0,4],[0,1,3]]),(200,160))
        forward=VisualTracker().initialize(image,[60,40,120,100]).update(moved)
        self.assertTrue(forward['reliable']);np.testing.assert_allclose(forward['box'],[64,43,124,103],atol=1)
        backward=VisualTracker().initialize(moved,[64,43,124,103]).update(image)
        self.assertTrue(backward['reliable']);np.testing.assert_allclose(backward['box'],[60,40,120,100],atol=1)

    def test_textureless_frame_and_relaxation_bounds(self):
        im=np.zeros((100,200,3),np.uint8)
        self.assertFalse(VisualTracker().initialize(im,[10,10,30,30]).update(im)['reliable'])
        region=relaxed_box([1,1,20,20],im.shape)
        self.assertEqual(region[:2],[0,0]);self.assertTrue(too_large(region,[1,1,20,20]))
