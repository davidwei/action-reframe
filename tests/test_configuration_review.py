import tempfile
import unittest
from configuration_review import report

class ConfigurationReviewTests(unittest.TestCase):
    def test_staleness_overrides_and_unknown_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            value=report(dict(analysis_fps=2,leveling_source='visual',output_width=640),folder,dict(analysis_fps=10,leveling_source='visual',output_width=640))
            rows={r['key']:r for r in value['rows']}
            self.assertEqual(rows['analysis_fps']['status'],'outdated')
            self.assertEqual(rows['output_width']['status'],'override')
            self.assertEqual(rows['leveling_source']['status'],'attention')
            self.assertEqual(rows['hold_seconds']['status'],'unknown')
            self.assertEqual(value['code']['analysis']['status'],'unknown')
            self.assertNotIn('api_url',rows)
