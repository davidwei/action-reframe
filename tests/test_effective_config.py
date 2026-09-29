import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from effective_config import merge,save


class EffectiveConfigTests(unittest.TestCase):
    def test_partial_nested_overrides_keep_all_defaults(self):
        defaults=json.loads((Path(__file__).resolve().parents[1]/'configs/defaults.json').read_text())
        result=merge(defaults,{'adaptive_verification':{'mode':'evaluation'},'tracking_selection':{'confidence_threshold':.25}})
        self.assertEqual(result['minimum_crop_short_side'],180)
        self.assertEqual(result['adaptive_verification']['tiny_box_ratio'],.5)
        self.assertEqual(result['adaptive_verification']['stable_seconds'],.5)
        self.assertEqual(result['tracking_selection']['agreement_iou'],.35)
        self.assertEqual(defaults['adaptive_verification']['mode'],'adaptive')

    def test_attempt_history_and_render_preserve_analysis_config(self):
        with tempfile.TemporaryDirectory() as folder:
            c=dict(output_dir=folder,minimum_crop_short_side=180,adaptive_verification={'mode':'adaptive','tiny_box_ratio':.5},ffmpeg='ffmpeg',_private='omit')
            with patch('code_version.current',return_value={'commit':'test'}):
                first=save(c,'analyze');original=first.read_bytes()
                c['minimum_crop_short_side']=240;second=save(c,'render')
            self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),original)
            self.assertEqual(json.loads((Path(folder)/'run_config.json').read_text())['minimum_crop_short_side'],180)
            latest=json.loads((Path(folder)/'effective_config.json').read_text())
            self.assertEqual(latest['minimum_crop_short_side'],240);self.assertNotIn('_private',latest)
            self.assertEqual(json.loads((Path(folder)/'render_config.json').read_text()),latest)
