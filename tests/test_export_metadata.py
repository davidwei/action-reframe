import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import av
import imageio_ffmpeg
from export_metadata import export_tags, ffmpeg_metadata_args, inspect_source, write_sidecar


class ExportMetadataTests(unittest.TestCase):
    def test_preserves_valid_metadata_not_old_encoding_or_orientation(self):
        source={'tags':{'creation_time':'2026-08-21T22:44:15Z','encoder':'DJI OsmoAction6',
                        'rotate':'90','timecode':'20:56:28;01','location':'private',
                        'com.apple.quicktime.location.ISO6709':'+37.4280-122.1303+008.641/',
                        'copyright':'Camera owner'},
                'streams':[{'type':'video','tags':{'model':'Action6','creation_time':'older'}}]}
        tags=export_tags(source)
        self.assertEqual(tags['creation_time'],'2026-08-21T22:44:15Z')
        self.assertEqual(tags['source_encoder'],'DJI OsmoAction6')
        self.assertEqual(tags['model'],'Action6')
        self.assertEqual(tags['location'],'private')
        self.assertIn('com.apple.quicktime.location.ISO6709',tags)
        self.assertEqual(tags['copyright'],'Camera owner')
        self.assertFalse({'rotate','timecode','encoder'} & tags.keys())

    def test_part_capture_times_are_shifted(self):
        source={'tags':{'creation_time':'2026-08-21T22:44:15.000000Z',
                        'com.apple.quicktime.creationdate':'2026-08-21T15:44:15-0700'},
                'streams':[{'type':'video','tags':{}}]}
        tags=export_tags(source,65.5)
        self.assertEqual(tags['creation_time'],'2026-08-21T22:45:20.500000Z')
        self.assertEqual(tags['com.apple.quicktime.creationdate'],'2026-08-21T15:45:20-0700')

    def test_real_export_tags_and_original_timecode_packet_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';output=root/'focused.mp4'
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=64x48:r=10',
                '-t','0.3','-c:v','libx264','-metadata','creation_time=2026-08-21T22:44:15Z',
                '-metadata','model=Test Camera','-timecode','01:00:00:00',
                '-movflags','+use_metadata_tags',str(source)],check=True)
            subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=red:s=64x48:r=10',
                '-t','0.3','-c:v','libx264',*ffmpeg_metadata_args(source),
                '-movflags','+use_metadata_tags',str(output)],check=True)
            actual=inspect_source(output)
            self.assertEqual(actual['tags']['model'],'Test Camera')
            self.assertTrue(actual['tags']['creation_time'].startswith('2026-08-21T22:44:15'))
            self.assertIn('source_encoder',actual['tags'])
            self.assertNotIn('timecode',actual['tags'])
            self.assertFalse(any(s['type']=='data' for s in actual['streams']))
            (root/'tracks.json').write_text('[]')
            write_sidecar(dict(video=str(source),output_dir=str(root),output_width=64,output_height=48))
            manifest=json.loads((root/'focused.metadata.json').read_text())
            self.assertEqual(manifest['frame_transforms'],'tracks.json')
            index=json.loads((root/'source_telemetry.json').read_text())
            payload=(root/'source_telemetry.bin').read_bytes()
            with av.open(str(source)) as container:
                original=[(bytes(p),p.pts) for p in container.demux([s for s in container.streams if s.type=='data']) if p.size]
            self.assertTrue(original,'Fixture must contain a timecode data track')
            self.assertEqual(len(index['packets']),len(original))
            for record,(data,pts) in zip(index['packets'],original):
                self.assertEqual(payload[record['offset']:record['offset']+record['size']],data)
                self.assertEqual(record['pts'],pts)
