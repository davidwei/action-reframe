import unittest
from tracking_selection import TrackSelector, frame_provenance


def row(frame=0,score=.9,box=None):
    return dict(frame=frame,time=frame/30,bbox=box or [100,100,200,200],
                confidence=score,visibility='visible')


class SelectionTests(unittest.TestCase):
    def fail_judge(self,*args):raise AssertionError('Adjudication should not be necessary')

    def test_agreement_and_sustained_advantage(self):
        s=TrackSelector({'switch_samples':3,'switch_advantage':.1})
        self.assertEqual(s.choose(row(),row(score=.8),self.fail_judge)['selected_path'],'raw_angle')
        for i in (15,30):
            r=s.choose(row(i,.7),row(i,.95),self.fail_judge)
            self.assertEqual(r['selected_path'],'raw_angle')
        r=s.choose(row(45,.7),row(45,.95),self.fail_judge)
        self.assertEqual(r['selected_path'],'leveled');self.assertTrue(r['path_switched'])

    def test_one_confident_then_both_lost(self):
        s=TrackSelector()
        r=s.choose(row(score=.2),row(),self.fail_judge)
        self.assertEqual(r['selected_path'],'leveled')
        r=s.choose(row(15,.1),row(15,.2),self.fail_judge)
        self.assertEqual(r['selected_path'],'neither');self.assertIsNone(r['bbox'])
        self.assertIn('tracking_selection_uncertain',r['selection_flags'])

    def test_confident_disagreement_requires_adjudication(self):
        s=TrackSelector();calls=[]
        def judge(candidates):
            calls.append(candidates)
            return {'choice':'leveled','confidence':.8,'reason':'correct sail identity'}
        r=s.choose(row(score=.99),row(score=.85,box=[600,100,700,200]),judge)
        self.assertEqual(len(calls),1);self.assertEqual(r['selected_path'],'leveled')
        self.assertEqual(r['confidence'],.8)
        self.assertIn('tracking_path_disagreement',r['selection_flags'])
        r=s.choose(row(15),row(15,box=[600,100,700,200]),lambda _: {'choice':'neither','confidence':.9})
        self.assertEqual(r['selected_path'],'neither')

    def test_motion_jump_and_failed_adjudication(self):
        s=TrackSelector({'max_center_speed':100,'motion_slack':10})
        s.choose(row(),row(score=.1),self.fail_judge)
        r=s.choose(row(15,.9,[700,100,800,200]),row(15,.1),lambda _: {'choice':'raw_angle','confidence':.4})
        self.assertEqual(r['selected_path'],'neither')
        self.assertIn('tracking_motion_discontinuity',r['selection_flags'])
        # Error-bearing and scene-cut observations must not win on confidence alone.
        a=row(30);a['error']='bad response'
        b=row(30);b['scene_cut']=True
        self.assertEqual(s.choose(a,b,self.fail_judge)['selected_path'],'neither')

    def test_provenance_for_interpolation_and_uncertain_frame(self):
        a=dict(row(0),selected_path='raw_angle');b=dict(row(4),selected_path='leveled')
        p=frame_provenance([a,b],5,[True,True,False,True,True])
        self.assertEqual(p[0]['selected_path'],'raw_angle')
        self.assertEqual(p[1]['selected_path'],'interpolated')
        self.assertEqual(p[1]['selection_source_paths'],['raw_angle','leveled'])
        self.assertEqual(p[2]['selected_path'],'neither')
        self.assertEqual(p[4]['selected_path'],'leveled')

class SelectedRenderTests(unittest.TestCase):
    def test_selected_track_drives_render_and_records_interpolation(self):
        import json,tempfile
        from pathlib import Path
        import cv2
        import numpy as np
        from reframe import load_config,prepare,write_json,render
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'sample.avi'
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
            for _ in range(5):writer.write(np.full((48,64,3),100,np.uint8))
            writer.release()
            config=root/'project.json'
            write_json(config,{'video':'sample.avi','output_dir':'output','reference_time':0,
                              'reference_box':[10,10,20,20],'target':'test','analysis_fps':2,
                              'tracking_mode':'dual','tracking_render_path':'selected',
                              'output_width':64,'output_height':48})
            c=load_config(config);meta=prepare(c);out=Path(c['output_dir'])
            selected=[dict(row(0),selected_path='raw_angle',shoreline=[0,500,1000,500],level_confidence=.9),
                      dict(row(4,box=[200,100,300,200]),selected_path='leveled',shoreline=[0,500,1000,500],level_confidence=.9)]
            write_json(out/'tracking_selected.json',selected)
            # A stale observations file must not override the selected track.
            write_json(out/'observations.json',[row(0,box=[700,700,900,900])])
            render(c)
            tracks=json.loads((out/'tracks.json').read_text())
            self.assertEqual(tracks[0]['selected_path'],'raw_angle')
            self.assertEqual(tracks[2]['selected_path'],'interpolated')
            self.assertEqual(tracks[4]['selected_path'],'leveled')
            np.testing.assert_allclose(tracks[0]['bbox'],[6.4,4.8,12.8,9.6])
            self.assertTrue((out/'comparison.mp4').exists())
