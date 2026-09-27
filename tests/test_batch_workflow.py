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

    def test_invalid_inputs_and_batch_atomic_validation(self):
        self.queue()
        write(self.root/'bad.json',dict(self.config,reference_box=[0,0,100,100]))
        with self.assertRaises(ValueError):self.batch.prepare('bad.json','bad',True)
        with self.assertRaises(ValueError):self.batch.enqueue(['project.json','bad.json'])
        self.assertEqual(len(self.batch.jobs()),1)
        with self.assertRaises(ValueError):self.batch.inputs('../outside.json')

if __name__=='__main__':unittest.main()
