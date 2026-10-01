import json
import tempfile
import unittest
from pathlib import Path
from result_shards import ResultShards,load_checkpoint,export_snapshot
from event_journal import EventJournal


def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)


class ShardTests(unittest.TestCase):
    def test_changed_shards_only_and_failed_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'anchor_checkpoint.json';store=ResultShards(out,180)
            state=dict(results={'1':dict(frame=1,bbox=None),'181':dict(frame=181,bbox=None)},events=[])
            store.save(cp,state,save);before=json.loads(cp.read_text())
            store.save(cp,state,save);self.assertEqual(before['result_shards'],json.loads(cp.read_text())['result_shards'])
            state['results']['1']=dict(frame=1,bbox=[1,2,3,4])
            def fail(path,value):
                if path==cp:raise OSError('Interrupted checkpoint')
                save(path,value)
            with self.assertRaises(OSError):store.save(cp,state,fail)
            self.assertIsNone(load_checkpoint(cp)['results']['1']['bbox'])
            store.save(cp,state,save);after=json.loads(cp.read_text())
            self.assertEqual(before['result_shards']['files']['1'],after['result_shards']['files']['1'])
            self.assertNotEqual(before['result_shards']['files']['0'],after['result_shards']['files']['0'])
            self.assertEqual(load_checkpoint(cp)['results']['1']['bbox'],[1,2,3,4])

    def test_journal_and_export_from_shards(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'anchor_checkpoint.json';store=ResultShards(out);journal=EventJournal(out)
            row=dict(frame=1,time=.1,bbox=[1,2,3,4],confidence=.8,candidates={'raw_angle':{},'leveled':{}})
            state=dict(results={'1':row},events=[dict(frame=1)],sample_indices=[0,1],stage='propagating')
            journal.checkpoint(state,lambda p,v:store.save(p,v,save),cp)
            disk=json.loads(cp.read_text());self.assertNotIn('results',disk);self.assertNotIn('events',disk)
            self.assertEqual(load_checkpoint(cp)['results']['1'],row)
            save(out/'meta.json',dict(fps=10));info=export_snapshot(out,save)
            self.assertEqual(info['frames'],2)
            rows=json.loads((out/'observations.json').read_text());self.assertIsNone(rows[0]['bbox']);self.assertEqual(rows[1]['bbox'],row['bbox'])
            self.assertEqual(json.loads((out/'tracking_comparison.json').read_text())[0]['frame'],1)

    def test_legacy_checkpoint_load(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'checkpoint.json';state=dict(results={'1':{'frame':1}},events=[])
            save(p,state);self.assertEqual(load_checkpoint(p),state)

    def test_corrupt_latest_shard_restores_whole_previous_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json';store=ResultShards(out)
            store.save(cp,dict(results={'1':{'frame':1}},queue=['old']),save)
            store.save(cp,dict(results={'2':{'frame':2}},queue=['new']),save)
            manifest=json.loads(cp.read_text())
            shard=out/next(iter(manifest['result_shards']['files'].values()))
            shard.write_text('{}')  # Valid JSON, but wrong checksum.
            with self.assertWarns(RuntimeWarning):state=load_checkpoint(cp)
            self.assertEqual(state['queue'],['old']);self.assertEqual(set(state['results']),{'1'})
            cp.write_text('')
            with self.assertWarns(RuntimeWarning):self.assertEqual(load_checkpoint(cp)['queue'],['old'])
            cp.with_name(cp.name+'.previous').write_text('')
            for history in (out/'checkpoint_history').glob('*.json'):history.write_text('')
            with self.assertRaisesRegex(ValueError,'Cannot recover checkpoint'):load_checkpoint(cp)

    def test_previous_checkpoint_scheduler_state_is_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json';store=ResultShards(out)
            state=dict(results={'1':{'frame':1}},queue=['old'])
            store.save(cp,state,save)
            state['queue'].append('new')
            store.save(cp,state,save)
            previous=json.loads(cp.with_name(cp.name+'.previous').read_text())
            self.assertEqual(previous['queue'],['old'])

    def test_repeated_generations_recover_and_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);cp=out/'checkpoint.json';store=ResultShards(out)
            for i in range(9):store.save(cp,dict(results={str(i):{'frame':i}},sequence=i),save)
            self.assertEqual(len(list((out/'checkpoint_history').glob('*_recent.json'))),5)
            self.assertEqual(len(list((out/'checkpoint_history').glob('*_hourly.json'))),1)
            cp.write_text('');cp.with_name(cp.name+'.previous').write_text('')
            with self.assertWarns(RuntimeWarning):self.assertEqual(load_checkpoint(cp)['sequence'],8)
