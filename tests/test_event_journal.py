import json
import tempfile
import unittest
from pathlib import Path
from event_journal import EventJournal


def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)


class JournalTests(unittest.TestCase):
    def test_migrate_append_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json'
            state=dict(events=[dict(frame=1,candidate={'bbox':[1,2,3,4]})],results={'1':{}})
            journal=EventJournal(out);journal.checkpoint(state,save,cp)
            first=journal.path.read_bytes()
            self.assertNotIn('events',json.loads(cp.read_text()))
            self.assertEqual(state['events'],[])
            state['events'].append(dict(frame=2))
            journal.checkpoint(state,save,cp)
            self.assertTrue(journal.path.read_bytes().startswith(first))
            restored=json.loads(cp.read_text());resumed=EventJournal(out,restored)
            resumed.checkpoint(restored,save,cp)
            self.assertEqual(resumed.count,2)
            self.assertEqual([json.loads(l)['frame'] for l in resumed.path.read_text().splitlines()],[1,2])

    def test_crash_after_append_before_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json';journal=EventJournal(out)
            state=dict(events=[dict(frame=1)]);journal.checkpoint(state,save,cp)
            state['events'].append(dict(frame=2))
            def fail(*args):raise OSError('simulated checkpoint failure')
            with self.assertRaises(OSError):journal.checkpoint(state,fail,cp)
            restored=json.loads(cp.read_text());resumed=EventJournal(out,restored)
            self.assertEqual(resumed.path.read_text(),'{"frame":1}\n')
            self.assertEqual(len(list(out.glob('events_uncommitted_*'))),1)
            restored['events']=[dict(frame=2)];resumed.checkpoint(restored,save,cp)
            self.assertEqual(resumed.count,2)

    def test_missing_committed_bytes_fail_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json';journal=EventJournal(out)
            state=dict(events=[dict(frame=1)]);journal.checkpoint(state,save,cp)
            journal.path.write_bytes(b'')
            with self.assertRaises(ValueError):EventJournal(out,json.loads(cp.read_text()))
