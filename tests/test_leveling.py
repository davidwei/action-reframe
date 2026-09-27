import json
from pathlib import Path
import tempfile
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from leveling import quaternion_roll, line_angle, angular_difference, visual_observation, build_comparison, extract_gyro


class LevelingTests(unittest.TestCase):
    def test_telemetry_schema_and_time_alignment(self):
        def msg(number, content):
            return bytes([number*8+2, len(content)])+content
        q=b''.join(bytes([i*8+5])+struct.pack('<f',v) for i,v in enumerate([1.,0.,0.,0.],1))
        payload=msg(1,msg(1,msg(1,b'dvtm_ac206.proto')))+msg(3,msg(2,msg(9,q)))
        class Packet:
            size=len(payload);pts=0;time_base=1/30
            def __bytes__(self):return payload
        class Container:
            streams=[SimpleNamespace(metadata={'handler_name':'CAM meta'})]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def demux(self,stream):return iter([Packet()])
        with patch('leveling.av.open',return_value=Container()):
            result=extract_gyro('synthetic',{'frames':1,'fps':30})
            self.assertEqual(result['frames'][0]['roll'],0)
            Packet.pts=10
            with self.assertRaisesRegex(ValueError,'timestamps'):extract_gyro('synthetic',{'frames':1,'fps':30})

    def test_axis_sign_and_invalid_quaternion(self):
        for angle in [-40,0,25]:
            xyzw=Rotation.from_euler('x',angle,degrees=True).as_quat()
            self.assertAlmostEqual(quaternion_roll(xyzw[[3,0,1,2]]),-angle)
        with self.assertRaises(ValueError):quaternion_roll([0,0,0,0])
        with self.assertRaises(ValueError):quaternion_roll([float('nan'),0,0,0])

    def test_visual_sign_and_aspect_ratio(self):
        self.assertAlmostEqual(line_angle([0,0,1000,1000],1920,1080),np.degrees(np.arctan2(1080,1920)))
        self.assertLess(line_angle([0,700,1000,300],1920,1080),0)
        with self.assertRaises(ValueError):line_angle([900,500,100,500],1920,1080)
        self.assertAlmostEqual(angular_difference(89,-89),-2)

    def test_independent_prompt_and_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);cv2.imwrite(str(p/'0000000.jpg'),np.zeros((48,64,3),np.uint8))
            c={'output_dir':temp,'api_url':'http://unused','video':'unused'}
            meta={'cache':temp,'width':64,'height':48,'fps':30}
            calls=[]
            def api(url,request):
                calls.append(request)
                content=request['messages'][0]['content']
                self.assertEqual(sum(v['type']=='image_url' for v in content),2)
                self.assertEqual(len(request['messages']),1)
                return {'choices':[{'message':{'content':json.dumps({'reference_line':[0,700,1000,300],
                    'cue':'shoreline','confidence':.95,'direction':'rises_right','note':'visible background'})}}]}
            first=visual_observation(c,meta,0,'test-model',api)
            second=visual_observation(c,meta,0,'test-model',api)
            self.assertEqual(len(calls),1)
            self.assertLess(first['roll'],0);self.assertEqual(second,first)
            self.assertEqual(first['confidence'],.95);self.assertEqual(first['orientation_confidence'],.6)
            visual_observation(c,meta,0,'different-model',api)
            self.assertEqual(len(calls),2)

    def test_gyro_final_divergence_and_unavailable_visual(self):
        with tempfile.TemporaryDirectory() as temp:
            gyro={'calibration':'test mapping','frames':[{'frame':i,'time':i/10,'roll':-20.} for i in range(10)]}
            Path(temp,'level_observations.json').write_text(json.dumps([{'frame':0,'roll':10,'reference_line':[0,0,1000,100],
                'orientation_confidence':.9,'confidence':.9,'cue':'horizon'}]))
            with patch('leveling.extract_gyro',return_value=gyro):
                rows=build_comparison({'output_dir':temp,'video':'unused','level_divergence_degrees':5},{'fps':10,'analysis_fps':10})
            self.assertEqual(rows[0]['final_roll'],-20)
            self.assertEqual(rows[0]['level_difference'],30)
            self.assertTrue(rows[0]['level_divergent'])
            self.assertIsNone(rows[-1]['qwen_roll'])
            self.assertEqual(rows[-1]['final_roll'],-20)
            self.assertFalse(rows[-1]['level_divergent'])


if __name__=='__main__':unittest.main()
