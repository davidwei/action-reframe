import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from batch_workflow import Batch, file_lock, read, write


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        writer=cv2.VideoWriter(str(self.root/'clip.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
        for _ in range(3):writer.write(np.zeros((48,64,3),np.uint8))
        writer.release()
        self.config={'video':'clip.avi','output_dir':'outputs/source','target':'green boat','reference_box':[10,10,30,30],'reference_time':0,'analysis_fps':2}
        write(self.root/'project.json',self.config);self.batch=Batch(self.root)

    def tearDown(self):self.temp.cleanup()

    def queue(self):
        self.batch.prepare('project.json','Small green sail, white hull',True)
        return self.batch.enqueue(['project.json'])[0]

    def starting(self,job):
        with self.batch.db() as db:db.execute("UPDATE jobs SET status='starting' WHERE id=?",(job,))

    def test_ready_revision_snapshot_and_duplicate(self):
        with self.assertRaises(ValueError):self.batch.enqueue(['project.json'])
        job=self.queue();self.assertEqual(self.batch.enqueue(['project.json']),[job])
        reopened=Batch(self.root);self.assertEqual(len(reopened.jobs()),1)
        c=read(self.root/reopened.jobs()[0]['config'])
        self.assertEqual(c['approved_target_description'],'Small green sail, white hull')
        self.assertNotEqual(c['output_dir'],str(self.root/'outputs/source'))
        write(self.root/'outputs/source/corrections.json',{'1':{'bbox':[1,2,10,20]}})
        self.assertTrue(self.batch.library()['projects'][0]['stale'])
        with self.assertRaises(ValueError):self.batch.enqueue(['project.json'])
        self.assertEqual(read(Path(c['output_dir'])/'corrections.json'),{})
        with self.assertRaises(ValueError):self.batch.adopt(job)

    def test_pause_failure_retry_and_recovery(self):
        job=self.queue();self.starting(job)
        self.batch.execute(job,[sys.executable,'-c','raise SystemExit(3)'])
        self.assertEqual(self.batch.jobs()[0]['status'],'failed')
        self.batch.action(job,'retry');self.starting(job)
        with file_lock(self.batch.folder/'locks'/(job+'.lock')) as held:
            self.assertTrue(held);self.batch.recover()
            self.assertEqual(self.batch.jobs()[0]['status'],'starting')
        self.batch.recover();self.assertEqual(self.batch.jobs()[0]['status'],'interrupted')
        self.batch.action(job,'retry');self.starting(job)
        self.batch.execute(job,[sys.executable,'-c','print("done")'])
        self.assertEqual(self.batch.jobs()[0]['status'],'succeeded')
        self.assertEqual(self.batch.jobs()[0]['attempts'],2)
        self.assertTrue(self.batch.paused());self.batch.pause(False);self.assertFalse(Batch(self.root).paused())

    def test_serial_worker_continues_after_failure_and_singleton(self):
        first=self.queue()
        write(self.root/'second.json',dict(self.config,output_dir='outputs/second'))
        self.batch.prepare('second.json','another target',True);second=self.batch.enqueue(['second.json'])[0]
        seen=[]
        def run(command):
            job=command[-1];seen.append(job)
            self.batch.execute(job,[sys.executable,'-c','pass'] if job==second else [sys.executable,'-c','raise SystemExit(1)'])
            return subprocess.CompletedProcess(command,0)
        original=subprocess.run
        def dispatch(command,**kwargs):
            if '--execute' in command:return run(command)
            return original(command,**kwargs)
        self.batch.pause(False)
        with file_lock(self.batch.folder/'worker.lock'):
            self.batch.worker();self.assertEqual(seen,[])
        with patch('batch_workflow.subprocess.run',side_effect=dispatch):self.batch.worker()
        self.assertEqual(seen,[first,second]);self.assertEqual([j['status'] for j in self.batch.jobs()],['failed','succeeded'])

    def test_adopt_preserves_source_and_requires_reapproval(self):
        job=self.queue();self.starting(job);self.batch.execute(job,[sys.executable,'-c','pass'])
        run=read(self.root/self.batch.jobs()[0]['config'])
        labels={'2':{'bbox':[1,2,20,30]}}
        write(Path(run['output_dir'])/'corrections.json',labels)
        self.batch.adopt(job)
        self.assertEqual(read(self.root/'outputs/source/corrections.json'),labels)
        self.assertFalse(self.batch.library()['projects'][0]['ready'])
        with self.assertRaises(ValueError):self.batch.adopt(job)

    def test_real_worker_renders_labeled_video_and_isolates_failure(self):
        import os
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from batch_workflow import SOURCE
        class ModelList(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path!='/v1/models':self.send_error(404);return
                blob=b'{"data":[{"id":"fixture-model"}]}'
                self.send_response(200);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),ModelList)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            good=dict(self.config,api_url=base+'/v1',tracking_mode='single',backward_recovery=False,
                      output_width=64,output_height=48,analysis_fps=10)
            write(self.root/'project.json',good)
            labels={str(i):{'bbox':[10,10,30,30]} for i in range(3)}
            write(self.root/'outputs/source/corrections.json',labels)
            write(self.root/'bad.json',dict(good,output_dir='outputs/bad',api_url=base+'/missing'))
            self.batch.prepare('bad.json','boat',True);self.batch.enqueue(['bad.json']);self.queue()
            self.batch.pause(False)
            env=dict(os.environ);env.pop('QWEN_API_URL',None)
            result=subprocess.run([sys.executable,str(SOURCE/'batch_workflow.py'),'--workspace',str(self.root),'--worker'],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            jobs=self.batch.jobs();self.assertEqual([j['status'] for j in jobs],['failed','succeeded'],jobs)
            output=Path(read(self.root/jobs[1]['config'])['output_dir'])
            self.assertTrue((output/'comparison.mp4').exists())
            self.assertTrue((output/'focused.mp4').exists())
            self.assertEqual(read(output/'corrections.json'),labels)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_five_states_and_discard_restore(self):
        project=self.batch.create_project('clip.avi')['project']
        def current():return next(p for p in self.batch.library()['projects'] if p['project']==project)
        self.assertEqual(current()['status'],'New');self.assertIn('Discard project',current()['actions'])
        self.batch.prepare(project,'green rectangle',False)
        self.assertEqual(current()['status'],'Draft')
        with self.assertRaises(ValueError):self.batch.prepare(project,'green rectangle',True)
        config=read(self.root/project);config['reference_box']=[10,10,30,30];write(self.root/project,config)
        self.batch.prepare(project,'green rectangle',True)
        self.assertEqual(current()['status'],'Ready')
        job=self.batch.enqueue([project])[0];self.assertEqual(current()['status'],'Processing')
        self.starting(job);self.batch.execute(job,[sys.executable,'-c','pass'])
        self.assertEqual(current()['status'],'Done')
        self.batch.discard(project)
        self.assertFalse(any(p['project']==project for p in self.batch.library()['projects']))
        self.assertTrue((self.root/project).exists());self.assertTrue((self.root/'clip.avi').exists())
        with self.assertRaises(ValueError):self.batch.enqueue([project])
        self.batch.restore(project);self.assertEqual(current()['status'],'Done')

    def test_discard_cancels_queued_and_defers_running_archive(self):
        first=self.queue();self.batch.discard('project.json')
        self.assertEqual(self.batch.jobs()[0]['status'],'cancelled')
        self.batch.restore('project.json');second=self.batch.enqueue(['project.json'])[0]
        self.starting(second)
        result=self.batch.discard('project.json');self.assertTrue(result['finishing'])
        project=self.batch.library()['projects'][0]
        self.assertEqual(project['status'],'Processing');self.assertTrue(project['discard_pending'])
        self.batch.execute(second,[sys.executable,'-c','pass'])
        self.assertEqual(self.batch.library()['projects'],[])
        self.assertEqual(self.batch.library()['archived'][0]['project'],'project.json')

    def test_description_review_shared_prompts_retry_cache_and_stale_labels(self):
        from description_review import review
        from crop_description import PROMPT
        from description_comparison import PROMPT as COMPARE
        write(self.root/'outputs/source/corrections.json',{'1':{'bbox':[12,12,32,32],'source_polygon_px':[[12,12],[32,12],[32,32],[12,32]]}})
        calls=[];value=.79
        def api(url,payload=None):
            if payload is None:return {'data':[{'id':'fixture'}]}
            calls.append(payload);content=payload['messages'][0]['content'];prompt=content[-1]['text']
            if prompt==PROMPT:
                self.assertEqual(sum(c['type']=='image_url' for c in content),1)
                result=json.dumps({'box_description':'A green target'})
            elif prompt.startswith('Compare Description A'):
                self.assertEqual(prompt,COMPARE.format(a=json.dumps('A green target'),b=json.dumps('A green target')))
                self.assertEqual(len(content),1)
                result=json.dumps(dict(match_score=value,target_present=True,target_complete=False,differences=['Clipped edge'],reason='Green appearance matches'))
            else:
                self.assertEqual(len(content),1);self.assertNotIn('ground truth',prompt);self.assertNotIn('candidate crop',prompt)
                result='A green target'
            return {'choices':[{'message':{'content':result}}]}
        initial=review(self.batch,'project.json')
        self.assertEqual(len(initial['references']),2)
        with patch('reframe.api',side_effect=api):
            result=review(self.batch,'project.json','draft')
            self.assertFalse(result['all_passed']);self.assertEqual(len(calls),5)
            self.assertTrue(all(r['confidence']==.79 for r in result['references']))
            self.assertFalse(result['approved'])
            value=.8
            retried=review(self.batch,'project.json','retry',result['description'])
            self.assertTrue(retried['all_passed']);self.assertEqual(len(calls),8)
            self.assertIn('Consistency-check results',calls[5]['messages'][0]['content'][0]['text'])
            self.assertEqual(sum(p['messages'][0]['content'][-1]['text']==PROMPT for p in calls),2)
            checked=review(self.batch,'project.json','check','A green target')
            self.assertTrue(checked['all_passed']);self.assertEqual(len(calls),10)
            with self.assertRaises(ValueError):review(self.batch,'project.json','retry','Edited text')
        self.assertEqual(review(self.batch,'project.json')['description'],'A green target')
        self.batch.prepare('project.json','A green target',True)
        self.assertEqual(review(self.batch,'project.json')['evidence_key'],initial['evidence_key'])
        write(self.root/'outputs/source/corrections.json',{'1':{'bbox':[14,12,32,32]}})
        stale=review(self.batch,'project.json')
        self.assertNotEqual(stale['evidence_key'],initial['evidence_key']);self.assertNotIn('description',stale)

    def test_absent_frames_are_blind_negative_checks_not_identity_evidence(self):
        import base64
        from description_review import review
        from crop_description import PROMPT
        from description_comparison import PROMPT as COMPARISON_PROMPT
        write(self.root/'outputs/source/corrections.json',{'1':{'bbox':None},'2':{'roll':0}})
        negative_score=.2;seen_sizes=[]
        def api(url,payload=None):
            if payload is None:return {'data':[{'id':'fixture'}]}
            content=payload['messages'][0]['content'];prompt=content[-1]['text']
            if prompt==PROMPT:
                image=cv2.imdecode(np.frombuffer(base64.b64decode(content[0]['image_url']['url'].split(',')[1]),np.uint8),cv2.IMREAD_COLOR)
                seen_sizes.append(image.shape[:2])
                result=json.dumps({'box_description':'NEGATIVE_SCENE' if image.shape[:2]==(48,64) else 'POSITIVE_BOAT'})
            elif prompt.startswith('Compare Description A'):
                negative='NEGATIVE_SCENE' in prompt
                self.assertEqual(prompt,COMPARISON_PROMPT.format(a=json.dumps('BOAT_IDENTITY'),b=json.dumps('NEGATIVE_SCENE' if negative else 'POSITIVE_BOAT')))
                result=json.dumps(dict(match_score=negative_score if negative else .8,target_present=True,
                                      target_complete=True,differences=[],reason='Visual text evidence'))
            else:
                self.assertIn('ONE photograph',prompt)
                self.assertIn('common subject',prompt)
                subject,contrast=prompt.split('Scenes without the subject (contrast only):',1)
                self.assertIn('POSITIVE_BOAT',subject);self.assertNotIn('NEGATIVE_SCENE',subject)
                self.assertIn('NEGATIVE_SCENE',contrast)
                result='BOAT_IDENTITY'
            return {'choices':[{'message':{'content':result}}]}
        with patch('reframe.api',side_effect=api):
            result=review(self.batch,'project.json','draft')
            self.assertEqual(len(result['references']),2) # Level-only correction is not an absence.
            self.assertTrue(result['all_passed'])
            negative=result['references'][1]
            self.assertFalse(negative['expected_present']);self.assertEqual(negative['image_scope'],'full_frame')
            self.assertEqual(negative['confidence'],.2);self.assertTrue(negative['passed'])
            self.assertEqual(seen_sizes,[(20,20),(48,64)])
            negative_score=.9
            result=review(self.batch,'project.json','check','BOAT_IDENTITY')
            self.assertFalse(result['all_passed'])
            self.assertEqual(result['references'][1]['confidence'],.9) # Never force score to zero from human label.
            self.assertFalse(result['references'][1]['passed'])
            self.assertEqual(len(seen_sizes),2) # Observations reused on recheck.
        self.assertFalse(review(self.batch,'project.json')['references'][1]['passed'])

    def test_invalid_inputs_and_batch_atomic_validation(self):
        self.queue()
        write(self.root/'bad.json',dict(self.config,reference_box=[0,0,100,100]))
        with self.assertRaises(ValueError):self.batch.prepare('bad.json','bad',True)
        with self.assertRaises(ValueError):self.batch.enqueue(['project.json','bad.json'])
        self.assertEqual(len(self.batch.jobs()),1)
        with self.assertRaises(ValueError):self.batch.inputs('../outside.json')

if __name__=='__main__':unittest.main()
