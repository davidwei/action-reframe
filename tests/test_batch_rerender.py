import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from batch_workflow import Batch, SOURCE, read, write
from reframe import load_config, prepare


class RerenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        writer=cv2.VideoWriter(str(self.root/'clip.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
        for _ in range(5):writer.write(np.full((48,64,3),100,np.uint8))
        writer.release()
        self.config=dict(video='clip.avi',output_dir='outputs/source',target='boat',reference_box=[10,10,30,30],
                         reference_time=0,analysis_fps=2,leveling_source='visual',output_width=64,output_height=48,api_url='http://127.0.0.1:9/v1')
        write(self.root/'project.json',self.config)
        c=load_config(self.root/'project.json');prepare(c)
        self.out=self.root/'outputs/source'
        write(self.out/'observations.json',[dict(frame=i,time=i/10,bbox=[150,200,500,650],confidence=.9,
                    shoreline=[0,500,1000,500],level_confidence=.9) for i in (0,4)])
        self.batch=Batch(self.root)

    def tearDown(self):self.temp.cleanup()

    def test_real_queued_rerender_without_model_or_approval_and_preserves_inputs(self):
        original=(self.out/'observations.json').read_bytes()
        write(self.out/'code_version.json',{'analysis':{'commit':'old','fingerprint':'old'}})
        self.assertTrue(self.batch.library()['projects'][0]['can_rerender'])
        jobs=self.batch.enqueue_rerender(['project.json']);job=jobs[0]
        with self.assertRaises(ValueError):self.batch.enqueue_rerender(['project.json'])
        self.assertFalse(self.batch.library()['projects'][0]['can_rerender'])
        c=read(self.root/self.batch.jobs()[0]['config']);output=Path(c['output_dir'])
        self.assertEqual(c['batch_stage'],'render')
        self.assertEqual((output/'observations.json').read_bytes(),original)
        self.assertTrue(Path(read(output/'meta.json')['cache']).is_relative_to(output))
        self.batch.pause(False)
        env=dict(os.environ,QWEN_API_URL='http://127.0.0.1:9/v1')
        result=subprocess.run([sys.executable,str(SOURCE/'batch_workflow.py'),'--workspace',str(self.root),'--worker'],
                              env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.batch.jobs()[0]['status'],'succeeded',(output/'job.log').read_text())
        self.assertTrue((output/'focused.mp4').exists());self.assertTrue((output/'comparison.mp4').exists())
        self.assertEqual((self.out/'observations.json').read_bytes(),original)
        self.assertFalse((self.out/'focused.mp4').exists())
        library=self.batch.library();self.assertEqual(library['projects'][0]['status'],'Done')
        self.assertEqual(library['jobs'][0]['stage'],'render')
        self.assertEqual(library['jobs'][0]['analysis_code_version']['status'],'older')
        self.assertEqual(library['jobs'][0]['render_code_version']['status'],'current')
        # Review corrections on the finished output are included in the next snapshot.
        labels={'2':{'bbox':[11,11,31,31]}}
        write(output/'review_corrections.json',labels)
        second=self.batch.enqueue_rerender(['project.json'])[0]
        row=next(j for j in self.batch.jobs() if j['id']==second)
        nextout=Path(read(self.root/row['config'])['output_dir'])
        self.assertEqual(read(nextout/'corrections.json'),labels)

    def test_rerenders_run_before_older_analysis_jobs(self):
        write(self.root/'analysis.json',dict(self.config,output_dir='outputs/analysis'))
        self.batch.prepare('analysis.json','boat',True)
        analysis=self.batch.enqueue(['analysis.json'])[0]
        rerender=self.batch.enqueue_rerender(['project.json'])[0]
        self.assertEqual(next(j for j in self.batch.jobs() if j['id']==rerender)['priority'],1)
        from batch_workflow import subprocess as batch_subprocess
        order=[]
        def execute(command):
            job=command[-1];order.append(job)
            with self.batch.db() as db:db.execute("UPDATE jobs SET status='succeeded' WHERE id=?",(job,))
        self.batch.pause(False)
        with patch.object(batch_subprocess,'run',side_effect=execute):self.batch.worker()
        self.assertEqual(order,[rerender,analysis])

    def test_invalid_selection_is_atomic_and_discarded_project_rejected(self):
        write(self.root/'empty.json',dict(self.config,output_dir='outputs/empty'))
        with self.assertRaises(ValueError):self.batch.enqueue_rerender(['project.json','empty.json'])
        self.assertEqual(self.batch.jobs(),[])
        self.batch.discard('project.json')
        with self.assertRaises(ValueError):self.batch.enqueue_rerender(['project.json'])

    def test_rerender_uses_unverified_per_frame_motion_for_framing(self):
        from optical_diagnostics import record
        from reframe import render
        record(self.out,dict(frame=2,reliable=True,bbox_px=[8,8,20,30],motion_quality=.8))
        original=(self.out/'observations.json').read_bytes()
        config=load_config(self.root/'project.json')
        config['minimum_crop_short_side']=24  # Tiny synthetic source; test motion-driven zoom independently.
        render(config)
        tracks=read(self.out/'tracks.json')
        np.testing.assert_allclose(tracks[2]['bbox'],[8,8,20,30])
        self.assertIn('optical_identity_unverified',tracks[2]['flags'])
        self.assertGreater(tracks[2]['camera_diagnostics']['target_retained_fraction'],.999)
        self.assertEqual((self.out/'observations.json').read_bytes(),original)

    def test_immediate_rerender_runs_while_analysis_active_and_queue_paused(self):
        import time
        from batch_workflow import file_lock
        with self.batch.db() as db:
            db.execute("INSERT INTO jobs (id,project,revision,status,created,updated,config) VALUES ('analysis','other.json','r','running',0,0,'other.json')")
        with file_lock(self.batch.folder/'worker.lock'),file_lock(self.batch.folder/'locks/analysis.lock'):
            job=self.batch.render_now('project.json')
            for _ in range(300):
                row=next(j for j in self.batch.jobs() if j['id']==job)
                if row['status'] in ('succeeded','failed'):break
                time.sleep(.05)
            self.assertEqual(row['status'],'succeeded',row.get('error'))
            self.assertEqual(row['lane'],'immediate')
            self.assertTrue(self.batch.paused())
            self.assertEqual(next(j for j in self.batch.jobs() if j['id']=='analysis')['status'],'running')

    def test_immediate_limit_and_worker_lane_and_recovery(self):
        from batch_workflow import file_lock
        with file_lock(self.batch.folder/'immediate-launch.lock'):
            job=self.batch.enqueue_rerender(['project.json'],immediate=True)[0]
            self.batch.recover()
            self.assertEqual(self.batch.jobs()[0]['status'],'starting')
        with file_lock(self.batch.folder/'locks'/(job+'.lock')):
            self.assertTrue(self.batch.active());self.assertFalse(self.batch.active(queued_lane_only=True))
            # Another project with saved analysis cannot start a second immediate job.
            write(self.root/'other.json',self.config)
            with self.assertRaisesRegex(ValueError,'already running'):
                self.batch.enqueue_rerender(['other.json'],immediate=True)
            self.batch.pause(False);self.batch.worker()
            self.assertEqual(self.batch.jobs()[0]['status'],'starting')
        self.batch.reconcile()
        self.assertEqual(self.batch.jobs()[0]['status'],'interrupted')
        self.batch.action(job,'retry')
        self.assertEqual(self.batch.jobs()[0]['lane'],'queue')
