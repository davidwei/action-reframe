import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from lookout.events import validate
from lookout.store import insert,connect,settings
from lookout.report import build,bounds
from lookout.http import post


class LookoutTests(unittest.TestCase):
    def test_schema_blocks_content_and_unknown_fields(self):
        for payload in [dict(kind='edit',text='private'),dict(kind='activity',x=20),dict(kind='view',project='/secret/file.mp4'),dict(kind='resource',value=float('nan'))]:
            with self.assertRaises(ValueError):validate(payload)
        self.assertEqual(validate(dict(kind='activity',mouse=True))['mouse'],True)

    def test_report_deduplicates_and_decisions_persist_without_scores(self):
        with tempfile.TemporaryDirectory() as root:
            lo,_=bounds('2026-09-28','America/Los_Angeles')
            e=validate(dict(id='one',kind='job',timestamp=lo+10,outcome='failed',source='queue_snapshot',job='job1'))
            insert(root,[e,e]);report=build(root,'2026-09-28')
            self.assertEqual(report['events'],1);self.assertEqual(len(report['operations']),1);self.assertEqual(report['ux'],[])
            self.assertNotIn('score',report['operations'][0])
            key=report['operations'][0]['key'];post(root,'decision',dict(key=key,state='dismissed'))
            self.assertEqual(build(root,'2026-09-28')['operations'],[])
            post(root,'decision',dict(key=key,state='open'))
            self.assertEqual(len(build(root,'2026-09-28')['operations']),1)

    def test_day_boundaries_handle_dst(self):
        lo,hi=bounds('2026-03-08','America/Los_Angeles');self.assertEqual(hi-lo,23*3600)
        lo,hi=bounds('2026-11-01','America/Los_Angeles');self.assertEqual(hi-lo,25*3600)

    def test_failed_transport_never_raises_and_payload_is_bounded(self):
        from lookout import events
        with tempfile.TemporaryDirectory() as root:
            with patch.object(events,'_root',Path(root)),patch.object(events,'_last_config',0):
                self.assertFalse(events.emit('stage',stage='prepare'))
            with self.assertRaises(ValueError):post(root,'events',{'events':[dict(kind='view')]*51})
            with self.assertRaises(ValueError):post(root,'events',{'events':[dict(kind='model')]})

    def test_disable_and_delete_require_collector_acknowledgment(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):post(root,'delete',{})
            post(root,'settings',{'enabled':False})
            with self.assertRaises(ValueError):post(root,'delete',{})
            p=Path(root)/'.lookout/heartbeat.json';p.write_text(json.dumps(dict(enabled=False,timestamp=time.time())))
            insert(root,[validate(dict(kind='view'))]);post(root,'delete',{})
            with connect(root) as db:self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)

    def test_overlapping_tabs_do_not_double_count_attention(self):
        with tempfile.TemporaryDirectory() as root:
            lo,_=bounds('2026-09-28','America/Los_Angeles')
            insert(root,[validate(dict(kind='activity',timestamp=lo+10,session=s,active_seconds=30)) for s in ['a','b']])
            self.assertEqual(build(root,'2026-09-28')['summary']['active_seconds_estimate'],30)
