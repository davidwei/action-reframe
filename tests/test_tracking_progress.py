import json,tempfile,unittest
from pathlib import Path
from tracking_progress import TrackingProgress,discovery_grid,progress_for_ui


class ProgressTests(unittest.TestCase):
    def test_unique_positions_attempts_retries_and_resolved_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            p=TrackingProgress(directory,'a',[0,5,10],range(0,11,2),0,10,.5)
            state={'stage':'propagating','anchors':[0],'queue':[{}],'coverage':{'0':{'manual':True}}}
            p.publish(state)
            p.record('optical',1,'accepted');p.record('optical',1,'rejected');p.record('optical',2,'errored')
            rejected={'comparison':{'target_present':True,'match_score':.4,'target_complete':True}}
            accepted={'comparison':{'target_present':True,'match_score':.8,'target_complete':True}}
            p.verification(2,rejected,'raw');p.verification(2,accepted,'raw');p.verification(2,accepted,'leveled')
            p.verification(4,{'error':'timeout'},'raw');p.verification(4,rejected,'leveled')
            p.verification(2,accepted,'raw',cached=True)
            p.record('discovery',5,'rejected');p.record('discovery',5,'accepted');p.record('discovery',7,'rejected')
            result=p.publish(state)
            self.assertEqual(result['verification']['examined'],2)
            self.assertEqual(result['verification']['accepted'],1);self.assertEqual(result['verification']['rejected'],1)
            self.assertEqual(result['verification']['attempts']['total'],5)
            self.assertEqual(result['verification']['attempts']['errored'],1)
            self.assertEqual(result['verification']['attempts']['cached'],1)
            self.assertEqual(result['optical']['examined'],2);self.assertEqual(result['optical']['accepted'],1)
            self.assertEqual(result['optical']['attempts']['total'],3)
            self.assertEqual(result['discovery']['examined'],1);self.assertEqual(result['discovery']['off_grid_examined'],1)
            self.assertEqual(result['discovery']['resolved_without_scan'],1);self.assertEqual(result['discovery']['remaining'],1)
            resumed=TrackingProgress(directory,'a',[0,5,10],range(0,11,2),0,10,.5,resuming=True)
            self.assertEqual(resumed.publish(state),result)
            reset=TrackingProgress(directory,'b',[0,5,10],range(11),0,10,.5)
            self.assertEqual(reset.publish(state)['optical']['examined'],0)

    def test_legacy_counts_do_not_invent_optical_or_verification_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            (out/'meta.json').write_text(json.dumps({'frames':31,'fps':30}))
            (out/'anchor_summary.json').write_text(json.dumps({'stage':'discovering','analysis_interval':[0,30],
                'coverage':{'0':{'manual':True},'15':{'independent_scanned':True}}}))
            result=progress_for_ui(out,{},dict(stage='anchor_discovering',total=11,discovery_fps=2))['coverage']
            self.assertEqual(result['discovery']['examined'],1);self.assertEqual(result['discovery']['total'],3)
            self.assertEqual(result['discovery']['resolved_without_scan'],1)
            self.assertFalse(result['optical']['available']);self.assertEqual(result['optical']['total'],31)
            self.assertFalse(result['verification']['available'])

    def test_actual_grid_rounding_and_clipped_interval(self):
        self.assertEqual(discovery_grid(0,30,30,2),[0,15,30])
        self.assertEqual(discovery_grid(7,25,30,2),[7,22,25])

    def test_optical_counts_only_frames_actually_visited_before_early_stop(self):
        from unittest.mock import Mock,patch
        import numpy as np
        from tracking_search import TrackingSearch
        with tempfile.TemporaryDirectory() as directory:
            progress=TrackingProgress(directory,'flow',[0,3],[0,3],0,3,.5)
            search=TrackingSearch({},dict(cache=directory,fps=30),{},'model',(None,None,None),None)
            search.progress=progress;search.frame=lambda i:np.zeros((100,200,3),np.uint8)
            search.localize=Mock(return_value={'frame':3})
            motion=dict(box=[20,20,60,60],uncertainty_px=1,motion_quality=.9)
            tracker=Mock();tracker.update.side_effect=[dict(motion,reliable=True),dict(motion,reliable=False)]
            with patch('tracking_search.VisualTracker') as factory:
                factory.return_value.initialize.return_value=tracker
                search.propagate({'frame':0,'bbox':[100,200,300,600]},3,1,{})
            counts=progress.publish({})['optical']
            self.assertEqual(counts['examined'],2);self.assertEqual(counts['attempts']['total'],2)
            self.assertEqual(counts['accepted'],1);self.assertEqual(counts['rejected'],1)
            self.assertNotIn('3',progress.frames['optical'])
            search.localize.assert_called_once()
