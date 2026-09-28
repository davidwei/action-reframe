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

class IntegrationTests(unittest.TestCase):
    def test_initial_reference_is_anchor_and_checkpoint_resumes(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from anchor_tracking import run_anchors
        with tempfile.TemporaryDirectory() as folder:
            c={'output_dir':folder,'video':'unused','reference_time':.5,'reference_box':[10,10,20,20],
               'analysis_fps':2,'leveling_source':'visual','anchor_tracking':{},'tracking_selection':{'confidence_threshold':.5}}
            meta={'cache':folder,'signature':'test','frames':5,'fps':2,'width':100,'height':100,'samples':[0,1,2,3,4]}
            def save(path,value):Path(path).write_text(json.dumps(value))
            with patch('anchor_tracking.TrackingSearch') as search:
                search.return_value.propagate.side_effect=lambda source,index,step,rows:row(index,localized=False)
                search.return_value.localize.side_effect=lambda index,rows:row(index,0)
                result=run_anchors(c,meta,'model',(None,None,save),None)
                self.assertTrue(result[1]['manual'])
                self.assertEqual(result[1]['bbox'],[100,100,200,200])
                count=search.return_value.propagate.call_count
                run_anchors(c,meta,'model',(None,None,save),None)
                self.assertEqual(search.return_value.propagate.call_count,count)
                self.assertEqual(json.loads(Path(folder,'analysis_progress.json').read_text())['stage'],'anchor_complete')

class FailedFrameReviewTests(unittest.TestCase):
    def test_output_failure_is_queued_and_discovery_continues_without_resume_loop(self):
        snapshots=[];calls=[]
        def discover(index,rows):
            calls.append(index)
            if index==1:return dict(frame=index,error='Model output was truncated during crop description')
            return row(index,0)
        s=AnchorScheduler(range(4),range(4),[],None,discover,lambda state:snapshots.append(copy.deepcopy(state)))
        s.run()
        self.assertEqual(calls,[0,1,2,3]);self.assertEqual(s.state['stage'],'complete')
        self.assertIn('1',s.state['analysis_failures'])
        self.assertTrue(s.state['coverage']['1']['independent_scanned'])
        self.assertIsNone(s.state['results']['1']['bbox'])
        AnchorScheduler(range(4),range(4),[],None,discover,lambda state:None,checkpoint=snapshots[-1]).run()
        self.assertEqual(calls,[0,1,2,3])

    def test_history_uses_successful_path_but_excludes_failed_frames(self):
        from tracking_search import TrackingSearch
        search=object.__new__(TrackingSearch);search.c={}
        good=row(1);failed=dict(row(2,0),bbox=None,analysis_failures=[{'error':'bad JSON'}])
        surviving=dict(row(3),analysis_failures=[{'path':'leveled','error':'bad JSON'}])
        rows={str(r['frame']):r for r in [good,failed,surviving]}
        self.assertEqual([r['frame'] for r in search.history(rows,4,'forward')],[1,3])
        self.assertEqual([r['frame'] for r in search.history(rows,0,'backward')],[3,1])

    def test_failed_path_does_not_destroy_good_path_and_transport_is_fatal(self):
        from analysis_failures import path_failures
        good=row(1);bad=dict(row(1),box_verification={'error':'truncated','model_error':{'kind':'truncated_output'}})
        candidates={'raw_angle':good,'leveled':bad}
        self.assertEqual(path_failures(candidates)[0]['path'],'leveled')
        self.assertEqual(good['confidence'],.9);self.assertEqual(bad['confidence'],0)
        with self.assertRaises(RuntimeError):path_failures({'raw_angle':dict(error='HTTP 503',model_error={'kind':'http_error'})})
