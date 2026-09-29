import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('monitor_queue',Path(__file__).resolve().parents[1]/'scripts/monitor_queue.py')
monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def run_monitor(self, statuses, errors, existing_marker=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.batch/monitor';folder.mkdir(parents=True)
            if existing_marker:(folder/'automatic-recovery.json').write_text('{}')
            calls=[];states=iter(statuses)
            def request(req, **kwargs):
                if isinstance(req,str):
                    current=next(states)
                    value={'paused':False,'jobs':[dict(id=str(i),project=str(i),status=s,error=errors[i],output_dir=f'out/{i}') for i,s in enumerate(current)]}
                else:
                    calls.append((req.full_url,json.loads(req.data)))
                    value={}
                return io.BytesIO(json.dumps(value).encode())
            with patch.object(monitor.urllib.request,'urlopen',side_effect=request),patch.object(monitor.time,'sleep'),patch.object(monitor,'lock_held',return_value=True),patch('sys.argv',['watch','--workspace',directory,'--recover-all-failed']),redirect_stdout(io.StringIO()):
                monitor.main()
            report=json.loads((folder/'latest.json').read_text())
            return calls,report

    def test_all_fail_retries_transient_once_but_not_deterministic(self):
        calls,report=self.run_monitor([
            ['running','queued'],['failed','failed'],['failed','failed'],['failed','failed']],
            ['Connection refused','ValueError: invalid gyro configuration'])
        self.assertEqual(calls,[('http://127.0.0.1:8765/api/batch/retry',{'id':'0'}),('http://127.0.0.1:8765/api/batch/start',{})])
        self.assertEqual(report['monitor_status'],'finished')

    def test_user_stop_and_persisted_recovery_do_not_retry(self):
        for terminal,marker in [('interrupted',False),('failed',True)]:
            calls,_=self.run_monitor([['running'],[terminal],[terminal]],['Connection refused'],marker)
            self.assertEqual(calls,[])
