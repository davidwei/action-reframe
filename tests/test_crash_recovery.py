"""Kill actual subprocesses at request/write boundaries; replay must remain safe."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from stage_records import Store
from durable_json import write_json
import json


@unittest.skipUnless(os.name=='posix','SIGKILL test')
class CrashRecoveryTests(unittest.TestCase):
    def run_and_kill(self,code,folder):
        p=subprocess.Popen([sys.executable,'-c',code,folder])
        try:
            for _ in range(200):
                if (Path(folder)/'ready').exists():break
                if p.poll() is not None:self.fail('Child exited before fault injection')
                time.sleep(.01)
            else:self.fail('Child did not reach fault injection')
            os.kill(p.pid,signal.SIGKILL);p.wait(timeout=5)
        finally:
            if p.poll() is None:p.kill();p.wait()

    def test_kill_during_model_compute_releases_lock_and_replays(self):
        with tempfile.TemporaryDirectory() as folder:
            self.run_and_kill('''import sys,time
from pathlib import Path
from stage_records import Store
def request(_):
 Path(sys.argv[1],'ready').touch();time.sleep(60)
Store(sys.argv[1]).run('model',1,{},request)
''',folder)
            value,record=Store(folder).run('model',1,{},lambda _: {'answer':42})
            self.assertEqual(value['answer'],42);self.assertFalse(record['reused'])

    def test_kill_before_atomic_replace_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';write_json(path,{'old':1})
            self.run_and_kill('''import sys,time
from pathlib import Path
import durable_json
def interrupted(*args):
 Path(sys.argv[1],'ready').touch();time.sleep(60)
durable_json.os.replace=interrupted
durable_json.write_json(Path(sys.argv[1],'state.json'),{'new':2})
''',folder)
            self.assertEqual(json.loads(path.read_text()),{'old':1})
            write_json(path,{'new':2});self.assertEqual(json.loads(path.read_text()),{'new':2})
