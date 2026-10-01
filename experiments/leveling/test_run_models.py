import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.leveling import run_models


class RestorationTests(unittest.TestCase):
    def test_launch_failure_restores_production(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config.json').write_text('{}')
            plan=dict(output=str(root/'output'),production_service='production.service',
                      production_endpoint='http://localhost:8000/v1',production_model='production',
                      vllm='missing-vllm',port=8001,candidates=[dict(label='candidate',model='candidate',path=str(root))])
            path=root/'plan.json';path.write_text(json.dumps(plan))
            with patch.object(run_models,'wait_model') as wait, patch.object(run_models.subprocess,'run') as command, patch.object(run_models.subprocess,'Popen',side_effect=OSError('launch failed')):
                run_models.run(path)
            actions=[call.args[0] for call in command.call_args_list]
            self.assertEqual(actions,[['systemctl','--user','stop','production.service'],['systemctl','--user','start','production.service']])
            self.assertEqual(wait.call_count,2)
            result=json.loads((root/'output/experiment.json').read_text())
            self.assertTrue(result['production_restored'])
            self.assertEqual(result['runs'][0]['status'],'failed')

    def test_missing_weights_do_not_stop_production(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'plan.json';path.write_text(json.dumps(dict(output=str(root/'output'),candidates=[dict(path=str(root/'absent'))])))
            with patch.object(run_models.subprocess,'run') as command:
                with self.assertRaises(ValueError):run_models.run(path)
            command.assert_not_called()


if __name__=='__main__':unittest.main()
