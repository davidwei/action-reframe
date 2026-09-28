import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import review_server as server


class ProjectSettingsLockTests(unittest.TestCase):
    def test_only_active_project_or_snapshot_is_locked(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'ROOT',Path(directory)), patch.object(server,'legacy_project',return_value=None):
            marker=Path(directory)/'.batch/queue.sqlite3';marker.parent.mkdir();marker.touch()
            jobs=[dict(project='active.json',config='.batch/run.json',status='running'),
                  dict(project='queued.json',config='.batch/queued.json',status='queued')]
            with patch('batch_workflow.Batch') as batch:
                batch.return_value.jobs.return_value=jobs
                self.assertTrue(server.project_running('active.json'))
                self.assertTrue(server.project_running('.batch/run.json'))
                self.assertFalse(server.project_running('queued.json'))
                self.assertFalse(server.project_running('other.json'))
            with patch.object(server,'legacy_project',return_value='legacy.json'):
                self.assertTrue(server.project_running('legacy.json'))

    def test_settings_api_edits_idle_project_while_other_job_runs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'ROOT',Path(directory)), patch.object(server,'batch_active',return_value=True), patch.object(server,'project_running',side_effect=lambda name:name=='active.json'):
            for name in ('active.json','idle.json','snapshot.json'):
                config=dict(output_dir='outputs/'+name,tracking_mode='anchor',anchor_tracking={'anchor_confidence':.85})
                if name=='snapshot.json':config['batch_input_revision']='revision'
                (Path(directory)/name).write_text(json.dumps(config))
            http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            def post(name):
                return urlopen(Request(f'http://127.0.0.1:{http.server_port}/api/settings',
                    data=json.dumps(dict(config=name,anchor_confidence=.9)).encode(),headers={'Content-Type':'application/json'}))
            try:
                with post('idle.json') as response:self.assertEqual(response.status,200)
                self.assertEqual(json.loads((Path(directory)/'idle.json').read_text())['anchor_tracking']['anchor_confidence'],.9)
                for name in ('active.json','snapshot.json'):
                    with self.assertRaises(HTTPError) as error:post(name)
                    self.assertEqual(error.exception.code,400)
                self.assertEqual(json.loads((Path(directory)/'active.json').read_text())['anchor_tracking']['anchor_confidence'],.85)
            finally:http.shutdown();http.server_close();thread.join()
