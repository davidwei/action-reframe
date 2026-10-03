import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from leveling_annotations import annotation_status, correction_series, row_at, rows_at
from reframe import load_config


class LevelingAnnotationTests(unittest.TestCase):
    def test_batch_snapshot_preserves_workspace_for_absolute_annotation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);run=root/'.batch/runs/job';run.mkdir(parents=True)
            video=root/'video.mp4';video.write_bytes(b'video')
            annotation=root/'outputs/level/leveling.json';annotation.parent.mkdir(parents=True);annotation.write_text('{}')
            config=run/'project.json';config.write_text(json.dumps(dict(video=str(video),output_dir=str(root/'outputs/run'),
                workspace_root=str(root),leveling_source='annotation',leveling_annotation=str(annotation),
                reference_time=0,reference_box=[0,0,1,1],target='object')))
            with patch('stage_records.configure'):
                loaded=load_config(config)
            self.assertEqual(loaded['_workspace_root'],str(root))
            self.assertEqual(Path(loaded['leveling_annotation']),annotation)

    def test_validates_shards_and_interpolates_only_for_consumers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'video.mp4';video.write_bytes(b'video')
            out=root/'outputs'/'level';out.mkdir(parents=True)
            rows=[
                dict(frame=0,time_seconds=0,correction_degrees_ccw=2,evidence_quality=.8,source='visual',flags=[]),
                dict(frame=1,time_seconds=.1,correction_degrees_ccw=None,evidence_quality=0,source='unknown',flags=['no_supported_level']),
                dict(frame=2,time_seconds=.2,correction_degrees_ccw=4,evidence_quality=.7,source='visual',flags=[]),
            ]
            shard=out/'rows.jsonl';shard.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            stat=video.stat();manifest=dict(schema='video-leveling-annotations/v1',status='partial',
                source=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns),metadata=dict(frames=3),
                counts=dict(estimated=2,unknown=1,needs_review=1),shards=[dict(path='rows.jsonl',start_frame=0,end_frame_exclusive=3,sha256=hashlib.sha256(shard.read_bytes()).hexdigest())])
            (out/'leveling.json').write_text(json.dumps(manifest))
            config=dict(video='video.mp4',leveling_source='annotation',leveling_annotation='outputs/level/leveling.json')
            status=annotation_status(root,config)
            self.assertEqual(status['status'],'Done');self.assertEqual(status['result_status'],'partial');self.assertAlmostEqual(status['coverage'],2/3)
            self.assertIsNone(row_at(root,config,1)['correction_degrees_ccw'])
            self.assertEqual([row['frame'] for row in rows_at(root,config,[2,0,2])],[2,0,2])
            angles,supported,quality,_=correction_series(root,config,3)
            self.assertEqual(angles.tolist(),[2,3,4]);self.assertEqual(supported.tolist(),[True,False,True])
            self.assertEqual(quality.tolist(),[.8,0,.7])


if __name__=='__main__':unittest.main()
