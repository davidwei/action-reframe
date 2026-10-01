import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import av
import numpy as np
import imageio_ffmpeg
from render_segments import Segments


class SegmentTests(unittest.TestCase):
    def test_resume_corruption_and_fractional_fps_audio_assembly(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);ffmpeg=imageio_ffmpeg.get_ffmpeg_exe();source=out/'source.mp4';fps=30000/1001;n=24
            subprocess.run([ffmpeg,'-y','-loglevel','error','-f','lavfi','-i',f'color=size=64x48:rate=30000/1001:duration={n/fps}',
                '-f','lavfi','-i',f'sine=frequency=440:duration={n/fps}','-c:v','libx264','-c:a','aac','-shortest',str(source)],check=True)
            c=dict(output_dir=folder,video=str(source),ffmpeg=ffmpeg,output_width=64,output_height=48,feather_pixels=4,render_segment_seconds=8/fps)
            meta=dict(frames=n,fps=fps);s=Segments(c,meta,{'camera':'one'})
            def frames(start,stop):
                for i in range(start,stop):
                    frame=np.full((48,64,3),i*8,np.uint8);yield frame,frame
            s.encode(0,8,frames(0,8))
            def interrupted():
                yield from frames(8,10)
                raise RuntimeError('power interrupted')
            with self.assertRaisesRegex(RuntimeError,'power interrupted'):s.encode(8,16,interrupted())
            resumed=Segments(c,meta,{'camera':'one'})
            self.assertTrue(resumed.ready(0,8));self.assertFalse(resumed.ready(8,16))
            resumed.encode(8,16,frames(8,16));resumed.encode(16,24,frames(16,24))
            from unittest.mock import patch
            with patch('render_segments.subprocess.run',side_effect=RuntimeError('assembly interrupted')):
                with self.assertRaisesRegex(RuntimeError,'assembly interrupted'):resumed.assemble([])
            self.assertTrue((resumed.folder/'000000000.json').exists())
            resumed.assemble([])
            with av.open(str(out/'focused.mp4')) as container:
                self.assertEqual(len(container.streams.audio),1)
                video=list(container.decode(video=0))
            self.assertEqual(len(video),n)
            np.testing.assert_allclose([f.to_ndarray(format='bgr24').mean() for f in video],np.arange(n)*8,atol=4)
            np.testing.assert_allclose(np.diff([float(f.pts*f.time_base) for f in video]),1/fps,atol=.0001)
            with av.open(str(out/'comparison.mp4')) as container:self.assertEqual(sum(1 for _ in container.decode(video=0)),n)
            s.paths(0)['focused'].write_bytes(b'broken')
            self.assertFalse(Segments(c,meta,{'camera':'one'}).ready(0,8))
            self.assertFalse(Segments(c,meta,{'camera':'changed'}).ready(8,16))
            progress=json.loads((out/'render_progress.json').read_text());self.assertEqual(progress['segments_reused'],1)
