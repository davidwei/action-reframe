import unittest
from tracking_selection import set_confidence_threshold, confidence_threshold, TrackSelector, frame_provenance

class ThresholdTests(unittest.TestCase):
    def test_validation_and_default(self):
        self.assertEqual(confidence_threshold({}),.5)
        for value in [-1,1.01,float('nan'),float('inf'),True,'50']:
            with self.subTest(value=value),self.assertRaises(ValueError):set_confidence_threshold({},value)
        config={};set_confidence_threshold(config,.7);self.assertEqual(confidence_threshold(config),.7)

    def test_selection_and_provenance_use_configured_threshold(self):
        row=dict(frame=0,time=0,bbox=[100,100,200,200],confidence=.6,visibility='visible')
        for threshold,expected in [(.5,'raw_angle'),(.7,'neither')]:
            selected=TrackSelector({'confidence_threshold':threshold}).choose(row,row,lambda _:self.fail('Unexpected adjudication'))
            self.assertEqual(selected['selected_path'],expected)
            provenance=frame_provenance([dict(row,selected_path='raw_angle')],1,[True],threshold)
            self.assertEqual(provenance[0]['selected_path'],expected)

    def test_anchor_threshold_settings(self):
        from review_server import set_anchor_options
        c={'tracking_selection':{'confidence_threshold':.5}}
        saved=set_anchor_options(c,{'anchor_confidence':.9,'discovery_fps':2,'tracking_mode':'anchor'})
        self.assertEqual(saved['anchor_confidence'],.9)
        self.assertEqual(c['anchor_tracking']['anchor_confidence'],.9)
        for invalid in [.4,1.1,True,float('nan')]:
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                set_anchor_options({'tracking_selection':{'confidence_threshold':.5}}, {'anchor_confidence':invalid})
