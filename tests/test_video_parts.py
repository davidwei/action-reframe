import json
from pathlib import Path
import tempfile
import unittest

import av
import imageio_ffmpeg

from video_parts import array_items,build_index,export,index,save_manifest


class VideoPartsTest(unittest.TestCase):
    def test_streams_json_array_across_small_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rows.json';rows=[{'frame':i,'text':'boat, ] '+str(i)} for i in range(17)]
            path.write_text('  '+json.dumps(rows,indent=2)+'\n')
            self.assertEqual(list(array_items(path,chunk_size=3)),rows)

    def test_splits_when_saved_geometry_starts_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tracks.json'
            rows=[
                {'frame':0,'bbox':[1,2,5,7],'selected_path':'raw'},
                {'frame':1,'bbox':[2,2,6,7],'selected_path':'interpolated'},
                {'frame':2,'bbox':[2,2,6,7],'selected_path':'neither'},
                {'frame':3,'bbox':None,'selected_path':'raw'},
                {'frame':4,'bbox':[1,1,8,8],'selected_path':'manual'},
            ]
            path.write_text(json.dumps(rows))
            parts=build_index(path,{'frames':5,'fps':10})
            self.assertEqual([(p['start_frame'],p['end_frame'],p['tracked']) for p in parts],[(0,2,True),(2,4,False),(4,5,True)])
            self.assertEqual(parts[0]['sources'],{'interpolated':1,'raw':1})
            self.assertAlmostEqual(parts[1]['duration_seconds'],.2)

    def fixture(self,root,frames=12,fps=6):
        output=root/'outputs'/'run';output.mkdir(parents=True)
        source=root/'original.mp4';source.write_bytes(b'original fixture')
        config=root/'project.json';config.write_text(json.dumps({'video':'original.mp4','output_dir':'outputs/run','project_name':'Boat'}))
        meta={'frames':frames,'fps':fps};(output/'meta.json').write_text(json.dumps(meta))
        rows=[{'frame':i,'bbox':[5,5,30,25] if i<frames//2 else None,'selected_path':'raw' if i<frames//2 else 'neither'} for i in range(frames)]
        (output/'tracks.json').write_text(json.dumps(rows));(output/'focused.mp4').write_bytes(b'focused fixture');(output/'comparison.mp4').write_bytes(b'comparison fixture')
        return config,output,meta,rows

    def test_render_manifest_and_runtime_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config,output,meta,rows=self.fixture(root)
            saved=save_manifest(output,meta,rows);self.assertEqual(len(saved),2)
            result=index(root,config)
            self.assertEqual(result['project_name'],'Boat');self.assertEqual(result['parts'][0]['filename'],'original_part1.mp4')
            self.assertEqual(result['parts'][1]['start_frame'],6);self.assertEqual(result['parts'][1]['save_status'],'not_saved')
            self.assertEqual(json.loads((output/'parts_index.json').read_text())['parts'],saved)

    def test_exports_only_selected_processed_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config,output,meta,rows=self.fixture(root,frames=12,fps=6)
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            import subprocess
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc=size=64x48:rate=6:duration=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-metadata','creation_time=2026-08-21T22:44:15Z',
                '-metadata','com.apple.quicktime.location.ISO6709=+37.4280-122.1303+008.641/',
                '-movflags','+use_metadata_tags',str(root/'original.mp4')],check=True)
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc=size=64x48:rate=6:duration=2',
                '-c:v','libx264','-pix_fmt','yuv420p',str(output/'focused.mp4')],check=True)
            save_manifest(output,meta,rows);status=export(root,config,1)
            target=root/'original_part1.mp4';self.assertEqual(status['status'],'done');self.assertTrue(target.is_file())
            with av.open(str(target)) as container:
                decoded=sum(1 for _ in container.decode(video=0))
                self.assertIn('com.apple.quicktime.location.ISO6709',container.metadata)
            self.assertGreaterEqual(decoded,5);self.assertLessEqual(decoded,7)


if __name__=='__main__':unittest.main()
