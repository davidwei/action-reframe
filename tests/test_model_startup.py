import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

spec=importlib.util.spec_from_file_location('wait_for_model',Path(__file__).resolve().parents[1]/'scripts/wait_for_model.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ModelStartupTests(unittest.TestCase):
    def test_ready_endpoint(self):
        with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(b'{"data":[{"id":"vision-model"}]}')) as request:
            module.wait('http://localhost:8000/v1/',10)
        self.assertEqual(request.call_args.args[0],'http://localhost:8000/v1/models')

    def test_refused_endpoint_explains_failure(self):
        with patch.object(module.urllib.request,'urlopen',side_effect=urllib.error.URLError('Connection refused')):
            with self.assertRaisesRegex(SystemExit,'Model unavailable at http://localhost:8000/v1/models'):
                module.wait('http://localhost:8000/v1',0)

    def test_empty_model_list_is_not_ready(self):
        with patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(b'{"data":[]}')):
            with self.assertRaisesRegex(SystemExit,'model list is empty'):
                module.wait('http://localhost:8000/v1',0)
