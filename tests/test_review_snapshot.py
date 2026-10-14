import json
from pathlib import Path
import tempfile
import unittest

from review_snapshot import build,frame,status


class ReviewSnapshotTest(unittest.TestCase):
    def test_random_access_and_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);meta={'frames':3,'fps':10};(out/'meta.json').write_text(json.dumps(meta))
            tracks=[
                {'frame':0,'bbox':[1,1,10,10],'crop_width':600,'crop_height':500},
                {'frame':1,'bbox':[2,2,11,11],'crop_width':300,'crop_height':200},
                {'frame':2,'bbox':None,'crop_width':600,'crop_height':500}]
            observations=[
                {'frame':0,'bbox':[1,1,10,10],'confidence':.9,'visibility':'visible'},
                {'frame':2,'bbox':None,'confidence':0,'visibility':'absent'}]
            comparison=[{'frame':0,'selected':observations[0],'raw_angle':observations[0],'leveled':observations[0]}]
            for name,rows in [('tracks',tracks),('observations',observations),('tracking_comparison',comparison)]:
                (out/f'{name}.json').write_text(json.dumps(rows))
            (out/'path_candidates.jsonl').write_text(json.dumps({'frame':0,'candidates':{'raw_angle_optical':{'bbox':[1,1,10,10],'confidence':.8}}})+'\n')
            (out/'optical_motion.jsonl').write_text(json.dumps({'frame':0,'reliable':True,'bbox_px':[1,1,10,10]})+'\n')
            manifest=build(out,meta,threshold=.5)
            self.assertEqual(manifest['navigation']['sampled'],[0,2])
            self.assertEqual(manifest['navigation']['tracked'],[0])
            self.assertEqual(manifest['navigation']['highqualitytracked'],[0])
            result=frame(out,0,.5)
            self.assertEqual(result['track']['frame'],0);self.assertEqual(result['observation']['confidence'],.9)
            self.assertIn('raw_angle_optical',result['path_candidates']);self.assertTrue(result['optical_motion']['reliable'])
            self.assertTrue(status(out,.5)['ready']);self.assertFalse(status(out,.7)['ready'])


if __name__=='__main__':unittest.main()
