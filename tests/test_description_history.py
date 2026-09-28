import json
import unittest
import test_batch_workflow as fixtures
from description_history import history
from batch_workflow import write


class DescriptionHistoryTests(unittest.TestCase):
    setUp=fixtures.BatchTests.setUp
    tearDown=fixtures.BatchTests.tearDown

    def test_each_save_and_approval_preserved_without_changing_active_description(self):
        self.batch.prepare('project.json','first saved')
        self.batch.prepare('project.json','approved version',True)
        self.batch.prepare('project.json','new draft')
        rows=history(self.batch,'project.json')['revisions']
        self.assertEqual([r['description'] for r in rows],['new draft','approved version','first saved'])
        self.assertEqual([r['kind'] for r in rows],['saved','approved','saved'])
        self.assertEqual(self.batch.preparation('project.json')['description'],'new draft')
        self.assertFalse(self.batch.preparation('project.json')['ready'])
        # Saving a restored revision appends history, never erases later revisions.
        self.batch.prepare('project.json',rows[-1]['description'])
        restored=history(self.batch,'project.json')['revisions']
        self.assertEqual(len(restored),4);self.assertEqual(restored[0]['description'],'first saved')

    def test_migration_preserves_existing_text_and_recovers_approved_job_snapshot(self):
        self.batch.prepare('project.json','historic approval',True)
        job=self.batch.enqueue(['project.json'])[0]
        with self.batch.db() as db:
            db.execute('DELETE FROM description_revisions')
            db.execute('UPDATE preparations SET payload=? WHERE project=?',(json.dumps(dict(description='legacy saved',ready=False,updated_at=1)), 'project.json'))
        self.batch.prepare('project.json','current text')
        rows=history(self.batch,'project.json')['revisions']
        self.assertEqual({r['description'] for r in rows},{'historic approval','legacy saved','current text'})
        self.assertEqual(len(history(self.batch,'project.json')['revisions']),len(rows))
        c=self.batch.jobs()[0]['config']
        with self.assertRaises(ValueError):history(self.batch,c)
