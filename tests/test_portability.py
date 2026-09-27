"""Exercise a fresh workspace using generated media, without a VL service."""
import json
import os
import shutil
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

import cv2
import numpy as np
import review_server
from reframe import load_config, prepare


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='action video ')
        self.root = Path(self.tmp.name)
        self.old_root = review_server.ROOT
        review_server.ROOT = self.root
        self.server = review_server.ThreadingHTTPServer(('127.0.0.1', 0), review_server.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        review_server.ROOT = self.old_root
        self.tmp.cleanup()

    def request(self, path, data=None):
        req = urllib.request.Request(self.base + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_empty_workspace_serves_ui_without_example_project(self):
        self.assertEqual(self.request('/api/videos'), [])
        state = self.request('/api/state')
        self.assertIsNone(state['project'])
        self.assertEqual(state['config']['video'], '')
        for path in ['/', '/compare', '/files/frame_analysis.js']:
            with urllib.request.urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_create_project_from_synthetic_video_and_relocate(self):
        video = self.root / 'sample.avi'
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
        self.assertTrue(writer.isOpened())
        for _ in range(3):
            writer.write(np.zeros((48, 64, 3), np.uint8))
        writer.release()
        self.assertEqual(self.request('/api/videos'), [video.name])
        result = self.request('/api/create', {'video':video.name, 'time':0,
            'bbox':[10, 10, 30, 30], 'target':'test subject'})
        config = json.loads((self.root / result['config']).read_text())
        self.assertEqual(config['video'], video.name)
        self.assertFalse(config['color_refinement'])
        self.assertEqual(config['tracking_selection']['confidence_threshold'],.5)
        saved=self.request('/api/settings',{'config':result['config'],'confidence_threshold':.6})
        self.assertEqual(saved['confidence_threshold'],.6)
        anchor=self.request('/api/settings',{'config':result['config'],'anchor_confidence':.9,'discovery_fps':2,'tracking_mode':'anchor'})
        self.assertEqual(anchor['anchor_confidence'],.9)
        self.assertEqual(json.loads((self.root/result['config']).read_text())['tracking_mode'],'anchor')
        self.assertEqual(json.loads((self.root/result['config']).read_text())['tracking_selection']['confidence_threshold'],.6)
        self.assertNotIn('target_hue', config)
        self.assertEqual(self.request('/api/state')['project'], result['config'])
        self.assertEqual(self.request('/api/info?video=sample.avi')['frames'], 3)
        moved = self.root / 'relocated'
        moved.mkdir()
        shutil.copyfile(video, moved / video.name)
        (moved / result['config']).write_text(json.dumps(config))
        with patch.dict(os.environ, {'QWEN_API_URL':'http://example.invalid:1234/v1/'}):
            loaded = load_config(moved / result['config'])
        self.assertEqual(loaded['video'], str(moved / video.name))
        self.assertEqual(loaded['api_url'], 'http://example.invalid:1234/v1')
        self.assertTrue(Path(loaded['output_dir']).is_relative_to(moved))
        metadata = prepare(loaded, max_time=0)
        self.assertEqual(metadata['frames'], 3)
        self.assertTrue((Path(metadata['cache']) / 'reference.jpg').exists())

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            review_server.local_path('../outside.mp4')

    def test_polygon_save_and_path_approval(self):
        out=self.root/'outputs'/'labels';out.mkdir(parents=True)
        config={'video':'sample.avi','output_dir':'outputs/labels','reference_time':0,'reference_box':[10,10,30,30],'target':'boat','output_width':64,'output_height':48}
        (self.root/'labels.json').write_text(json.dumps(config))
        (out/'meta.json').write_text(json.dumps({'frames':2,'width':64,'height':48,'fps':10}))
        (out/'tracks.json').write_text(json.dumps([{'center':[32,24],'crop_height':48,'roll':20,'bbox':None}]*2))
        writer=cv2.VideoWriter(str(self.root/'sample.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
        for _ in range(2):writer.write(np.zeros((48,64,3),np.uint8))
        writer.release()
        preview=self.request('/api/review-frame?config=labels.json&frame=0')
        self.assertTrue(preview['image'].startswith('data:image/jpeg;base64,'))
        points=[[20,15],[40,15],[40,30],[20,30]]
        self.request('/api/correct',{'config':'labels.json','frame':0,'polygon':points,'space':'processed','view_signature':preview['geometry']['signature']})
        saved=json.loads((out/'corrections.json').read_text())['0']
        self.assertEqual(saved['selection_space'],'processed')
        np.testing.assert_allclose(saved['processed_polygon_px'],points,atol=.001)
        candidate={'bbox':[100,100,400,400],'source_polygon_px':[[7,5],[25,6],[24,18],[6,17]]}
        (out/'tracking_comparison.json').write_text(json.dumps([{'frame':1,'raw_angle':candidate,'leveled':candidate}]))
        self.request('/api/correct',{'config':'labels.json','frame':1,'approve_path':'raw_angle'})
        saved=json.loads((out/'corrections.json').read_text())['1']
        self.assertEqual(saved['approved_path'],'raw_angle')
        self.assertEqual(saved['source_polygon_px'],candidate['source_polygon_px'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/correct',{'config':'labels.json','frame':0,'approve_path':'raw_angle'})
        self.request('/api/correct',{'config':'labels.json','frame':1,'approve_path':'leveled'})
        saved=json.loads((out/'corrections.json').read_text())['1']
        np.testing.assert_allclose(saved['bbox'],[6.4,4.8,25.6,19.2],atol=.001)
        self.assertEqual(saved['approved_path'],'leveled')
        self.request('/api/correct',{'config':'labels.json','frame':1,'bbox':None})
        saved=json.loads((out/'corrections.json').read_text())['1']
        self.assertIsNone(saved['bbox']);self.assertIsNone(saved['source_polygon_px'])


if __name__ == '__main__':
    unittest.main()
