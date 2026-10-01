import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from durable_json import write_json

class DurableJsonTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_commit_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';write_json(path,{'old':1})
            with patch('durable_json.os.replace',side_effect=OSError('disk error')):
                with self.assertRaises(OSError):write_json(path,{'new':2})
            self.assertEqual(json.loads(path.read_text()),{'old':1})
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_file_sync_precedes_replace_and_directory_sync_follows(self):
        with tempfile.TemporaryDirectory() as folder:
            import durable_json
            events=[];replace=durable_json.os.replace
            with patch('durable_json.os.fsync',side_effect=lambda _:events.append('sync')):
                with patch('durable_json.os.replace',side_effect=lambda a,b:(events.append('replace'),replace(a,b))[-1]):
                    write_json(Path(folder)/'state.json',{})
            self.assertEqual(events,['sync','replace','sync'])
