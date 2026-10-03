import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from two_path_tracking import TwoPathSearch,leveled_transform,rebase_tracker
from visual_tracking import VisualTracker
from path_candidates import combine,choose,load,apply_to_render
from analysis_scheduler import AnchorScheduler


def row(frame,path,method,score,box=None):
    optical=method=='optical'
    return dict(frame=frame,time=frame/30,path=path,candidate_id=path+'_'+method,bbox=box or [200,200,400,500],
        confidence=score,visibility='visible',localized=not optical,motion_reliable=optical,
        identity_verified=True,analysis_source='flow_crop_validation' if optical else 'full_frame_detection')

class TwoPathTests(unittest.TestCase):
    def test_optical_stop_is_per_path_and_uses_motion_quality(self):
        search=object.__new__(TwoPathSearch);search.optical_best={}
        old=dict(row(5,'raw_angle','optical',.1),motion_quality=.8)
        search.remember_optical(old)
        self.assertTrue(search.optical_dominated(dict(old,confidence=.99,motion_quality=.8)))
        self.assertTrue(search.optical_dominated(dict(old,motion_quality=.7)))
        self.assertFalse(search.optical_dominated(dict(old,motion_quality=.9)))
        self.assertFalse(search.optical_dominated(dict(old,path='leveled')))
        self.assertFalse(search.optical_dominated(dict(old,frame=6)))
        search.remember_optical(dict(row(6,'raw_angle','detection',1),motion_quality=1))
        self.assertFalse(search.optical_dominated(dict(old,frame=6)))

    def test_scheduler_does_not_restart_a_stopped_path(self):
        calls=[]
        def propagate(source,i,step,rows):
            calls.append((i,source.get('_propagation_paths')))
            candidate=row(i,'leveled','optical',.7)
            return dict(combine(None,dict(frame=i,four_candidates={'leveled_optical':candidate})),
                        propagation_paths=['leveled'] if i==1 else [])
        anchor=dict(frame=0,bbox=[100,100,300,300],confidence=1,manual=True,visibility='visible')
        scheduler=AnchorScheduler([0,1,2,3],[],[anchor],propagate,lambda *a:None,lambda s:None,
                                 dict(two_path_tracking=True,anchor_confidence=.85))
        scheduler.run()
        self.assertEqual(calls,[(1,None),(2,['leveled'])])

    def test_separate_winners_and_render_selection(self):
        records={r['candidate_id']:r for r in [row(1,'raw_angle','detection',.6),row(1,'raw_angle','optical',.8),row(1,'leveled','detection',.9),row(1,'leveled','optical',.7)]}
        result=combine(None,dict(frame=1,four_candidates=records))
        self.assertEqual(result['path_results']['raw_angle']['candidate_id'],'raw_angle_optical')
        self.assertEqual(result['path_results']['leveled']['candidate_id'],'leveled_detection')
        self.assertEqual(result['candidate_id'],'leveled_detection')
        failed=dict(frame=1,bbox=None,confidence=0,four_candidates={'raw_angle_detection':dict(row(1,'raw_angle','detection',0),bbox=None)})
        merged=combine(result,failed)
        self.assertEqual(len(merged['four_candidates']),4)
        self.assertEqual(merged['candidate_id'],'leveled_detection')
        with tempfile.TemporaryDirectory() as folder:
            from path_candidates import record
            record(folder,1,records)
            self.assertEqual(apply_to_render([],folder,.5)[0]['candidate_id'],'leveled_detection')
            human=dict(frame=1,bbox=None,manual=True)
            self.assertIsNone(apply_to_render([human],folder,.5)[0]['bbox'])

    def test_accepted_discovery_seeds_both_directions_below_high_threshold(self):
        calls=[]
        def discover(i,rows):return combine(None,dict(frame=i,four_candidates={'raw_angle_detection':row(i,'raw_angle','detection',.7)}))
        def propagate(source,i,step,rows):
            calls.append((source['frame'],i));return dict(frame=i,time=i,bbox=None,confidence=0,visibility='uncertain',four_candidates={})
        scheduler=AnchorScheduler([0,1,2],[1],[],propagate,discover,lambda s:None,dict(two_path_tracking=True,anchor_confidence=.85))
        scheduler.run();self.assertEqual(set(calls),{(1,0),(1,2)});self.assertEqual(scheduler.state['anchors'],[])

    def test_pivot_rebase_preserves_raw_feature_positions_without_zoom(self):
        image=np.random.default_rng(5).integers(0,255,(100,160,3),dtype=np.uint8)
        a,size=leveled_transform(160,100,np.array([50,50]),12)
        b,newsize=leveled_transform(160,100,np.array([80,35]),12)
        self.assertEqual(size,newsize);self.assertAlmostEqual(np.linalg.det(a[:,:2]),1.)
        raw=np.array([[30,20],[80,20],[80,70],[30,70]])
        from dual_tracking import transform_points
        poly=transform_points(raw,a)
        tracker=VisualTracker().initialize(cv2.warpAffine(image,a,size),np.r_[poly.min(axis=0),poly.max(axis=0)],poly.tolist())
        np.testing.assert_allclose(transform_points(tracker.corners,cv2.invertAffineTransform(a)),raw,atol=1e-6)
        before=transform_points(tracker.points.reshape(-1,2),cv2.invertAffineTransform(a))
        rebase_tracker(tracker,image,a,b,size)
        after=transform_points(tracker.points.reshape(-1,2),cv2.invertAffineTransform(b))
        np.testing.assert_allclose(before,after,atol=1e-4)

    def test_each_branch_tracks_own_seed_and_records_intermediate_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cache=out/'cache';cache.mkdir()
            image=np.random.default_rng(6).integers(0,255,(100,160,3),dtype=np.uint8)
            cv2.imwrite(str(cache/'reference.jpg'),image[20:60,20:60])
            images=[np.roll(image,i,axis=1) for i in range(4)]
            c=dict(output_dir=str(out),target='object',api_url='test',adaptive_verification=dict(mode='off'),anchor_tracking=dict(discovery_fps=2),tracking_selection=dict(confidence_threshold=.5))
            meta=dict(width=160,height=100,frames=4,fps=30,cache=str(cache))
            helpers=(lambda c,m,i:images[i],None,lambda p,v:p.write_text(json.dumps(v)))
            search=TwoPathSearch(c,meta,dict(frames=[dict(roll=0) for _ in images]),'test',helpers,None)
            source=combine(None,dict(frame=0,four_candidates={r['candidate_id']:r for r in [row(0,'raw_angle','detection',.8,[100,100,400,600]),row(0,'leveled','detection',.9,[500,200,850,700])]}))
            def verify(*args):return dict(version=7,comparison=dict(match_score=.8,target_present=True,target_complete=True,localization_support='supported',exclusion_check='pass'),description={})
            with patch('two_path_tracking.verify_box',side_effect=verify),patch.object(search,'detect',side_effect=AssertionError('Reliable tracking must not trigger recovery')):
                result=search.propagate(source,3,1,{'0':source})
            self.assertEqual(len(result['path_results']),2)
            records=load(out)
            self.assertEqual(set(records),{'1','2','3'})
            self.assertEqual(records['1']['raw_angle_optical']['confidence_measurement'],'inherited')
            self.assertEqual(records['3']['leveled_optical']['confidence_measurement'],'measured')
            self.assertLess(result['path_results']['raw_angle']['bbox'][0],result['path_results']['leveled']['bbox'][0])
            self.assertEqual(records['3']['leveled_optical']['rotation_applied'],0)
            # Revisit identical source/frames: stop both paths at the first overlap,
            # without another verification or independent recovery.
            with patch('two_path_tracking.verify_box',side_effect=AssertionError('No repeat verification')),patch.object(search,'detect',side_effect=AssertionError('No recovery for dominated branch')):
                repeat=search.propagate(source,3,1,{'0':source})
            self.assertEqual(repeat['propagation_paths'],[])
            self.assertEqual(set(repeat['propagation_stops']),{'raw_angle','leveled'})
            self.assertTrue(all(v['frame']==1 for v in repeat['propagation_stops'].values()))

    def test_repaired_position_stops_both_optical_branches(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache';cache.mkdir()
            image=np.random.default_rng(77).integers(0,255,(80,120,3),dtype=np.uint8)
            cv2.imwrite(str(cache/'reference.jpg'),image)
            c=dict(output_dir=folder,target='object',adaptive_verification=dict(mode='off'),
                   tracking_selection=dict(confidence_threshold=.5))
            meta=dict(width=120,height=80,frames=2,fps=30,cache=str(cache),source_repaired_frames=[1])
            helpers=(lambda c,m,i:image,None,lambda p,v:None)
            search=TwoPathSearch(c,meta,dict(frames=[dict(roll=0),dict(roll=0)]),'test',helpers,None)
            source=combine(None,dict(frame=0,four_candidates={
                r['candidate_id']:r for r in [row(0,'raw_angle','detection',.8),row(0,'leveled','detection',.8)]}))
            with patch.object(search,'detect',return_value=None):
                result=search.propagate(source,1,1,{'0':source})
            self.assertEqual(set(result['propagation_stops']),{'raw_angle','leveled'})
            self.assertTrue(all(stop['reason']=='source_frame_repaired' for stop in result['propagation_stops'].values()))
            self.assertFalse(result['four_candidates'])


    def test_tiny_adaptive_skips_but_evaluation_keeps_actual_checks(self):
        for mode,expected_calls in [('adaptive',0),('evaluation',4)]:
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder);cache=out/'cache';cache.mkdir()
                image=np.random.default_rng(66).integers(0,255,(100,160,3),dtype=np.uint8)
                cv2.imwrite(str(cache/'reference.jpg'),image[20:60,20:60])
                images=[np.roll(image,i,axis=1) for i in range(7)]
                c=dict(output_dir=folder,target='object',api_url='test',analysis_fps=10,
                    adaptive_verification=dict(mode=mode),minimum_crop_short_side=180,
                    tracking_selection=dict(confidence_threshold=.5))
                meta=dict(width=160,height=100,frames=7,fps=30,cache=str(cache))
                helpers=(lambda c,m,i:images[i],None,lambda p,v:p.write_text(json.dumps(v)))
                search=TwoPathSearch(c,meta,dict(frames=[dict(roll=0) for _ in images]),'test',helpers,None)
                source=dict(frame=0,manual=True,bbox=[125,200,375,600],confidence=1,visibility='visible')
                result=dict(version=7,comparison=dict(match_score=.8,target_present=True,localization_support='supported',exclusion_check='pass'),description=dict(composition='isolated_subject'))
                with patch('two_path_tracking.verify_box',return_value=result) as verify,patch.object(search,'detect',return_value=None):
                    first=search.propagate(source,3,1,{'0':source})
                    second=search.propagate(first,6,1,{'0':source,'3':first})
                self.assertEqual(verify.call_count,expected_calls)
                for r in second['four_candidates'].values():
                    self.assertTrue(r['verification_schedule']['tiny'])
                    self.assertFalse(r['verification_schedule']['proposed_verify'])
                    self.assertEqual(r['verification_schedule_state']['last_pass'],0)
                    self.assertEqual(r['verification_schedule']['performed'],mode=='evaluation')
                    if mode=='adaptive':
                        self.assertFalse(r['identity_verified']);self.assertEqual(r['confidence_frame'],0)

    def test_discovery_grid_is_capped_at_two_fps(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache';cache.mkdir()
            search=TwoPathSearch(dict(output_dir=folder,anchor_tracking=dict(discovery_fps=10)),dict(cache=str(cache),frames=61,fps=30),{},'model',(None,None,None),None)
            self.assertEqual(sorted(search.discovery),[0,15,30,45,60])
            self.assertIsNone(search.detect(1,{},'forward','raw_angle'))

    def test_recovery_without_box_uses_image_center_not_historical_box(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'cache';cache.mkdir()
            cv2.imwrite(str(cache/'reference.jpg'),np.zeros((10,10,3),np.uint8))
            c=dict(output_dir=folder,target='object',anchor_tracking={})
            meta=dict(cache=str(cache),frames=31,fps=30,width=160,height=100)
            search=TwoPathSearch(c,meta,dict(frames=[dict(roll=20)]*31),'model',(None,None,None),None)
            rows={'0':combine(None,dict(frame=0,four_candidates={'leveled_detection':row(0,'leveled','detection',.9)}))}
            captured=[]
            def observe(c,*args,**kwargs):
                captured.append(c['_analysis_view']);return dict(frame=15,bbox=None,confidence=0)
            with patch('two_path_tracking.observe_path',side_effect=observe):search.detect(15,rows,'forward','leveled')
            matrix=np.asarray(captured[0]['matrix']);size=captured[0]['size']
            np.testing.assert_allclose(matrix[:,:2]@np.array([80,50])+matrix[:,2],np.array(size)/2)
            self.assertAlmostEqual(np.linalg.det(matrix[:,:2]),1.)
