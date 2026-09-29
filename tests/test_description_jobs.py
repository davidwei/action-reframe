import tempfile
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from description_jobs import run,status,paths,save

class DescriptionJobTests(unittest.TestCase):
    def test_navigation_status_duplicate_guard_and_parallel_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);batch=SimpleNamespace(folder=root/'.batch',path=lambda p:root/p)
            started=threading.Event();finish=threading.Event()
            def work():
                started.set()
                if not finish.wait(5):raise RuntimeError('Test timed out')
                return {'all_passed':True}
            with ThreadPoolExecutor(2) as pool:
                first=pool.submit(run,batch,'a.json','check',work)
                try:
                    self.assertTrue(started.wait(2))
                    self.assertEqual(status(batch,'a.json')['status'],'running')
                    with self.assertRaisesRegex(ValueError,'already running'):
                        run(batch,'./a.json','draft',lambda:None)
                    second=pool.submit(run,batch,'b.json','check',lambda:{'all_passed':False})
                    self.assertEqual(second.result(timeout=2)['job']['status'],'succeeded')
                    self.assertEqual(status(batch,'a.json')['status'],'running')
                finally:finish.set()
                self.assertEqual(first.result(timeout=2)['job']['status'],'succeeded')
            self.assertEqual(status(batch,'a.json')['status'],'succeeded')

    def test_failure_and_interrupted_job_do_not_leave_controls_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);batch=SimpleNamespace(folder=root/'.batch',path=lambda p:root/p)
            with self.assertRaisesRegex(RuntimeError,'model failure'):
                run(batch,'a.json','check',lambda:(_ for _ in ()).throw(RuntimeError('model failure')))
            self.assertEqual(status(batch,'a.json')['error'],'model failure')
            _,path=paths(batch,'a.json');save(path,{'status':'running','action':'check'})
            self.assertEqual(status(batch,'a.json')['status'],'interrupted')
            self.assertEqual(run(batch,'a.json','check',lambda:{})['job']['status'],'succeeded')
