from video_fixture import make_video
import io,unittest,tempfile,csv
from pathlib import Path
from unittest.mock import patch, Mock
import numpy as np
from PIL import Image
from keyscope.config import DEFAULTS,geometry,validate_controls
from keyscope.score import Debouncer
from keyscope.converter import convert_score
from keyscope.engine import render_preview
from keyscope import engine
from keyscope.jobs import Job
from keyscope.config import ROOT


class RecognitionTests(unittest.TestCase):
    def test_debounce_first_timestamp_not_sliding_and_per_key(self):
        d=Debouncer(50)
        self.assertEqual(d.accept(0,['D','Z']),('D','Z'))
        self.assertEqual(d.accept(.03,['D','G']),('G',))
        self.assertEqual(d.accept(.05,['D']),())
        self.assertEqual(d.accept(.06,['D','G']),('D',))
        self.assertEqual(Debouncer(0).accept(0,['D']),('D',))

    def test_disabled_keys_and_moved_region_in_crop(self):
        cfg={**DEFAULTS,'model_path':'models/faster_rcnn.onnx','disabled_keys':['Q'],'regions':{**DEFAULTS['regions'],'W':[0,0,120,90]}}
        roi,regions=geometry(cfg,1920,1080)
        self.assertNotIn('Q',regions);self.assertEqual(regions['W'],[0,0,120,90]);self.assertEqual(roi[:2],[0,0])
        for bad in ('Q',['K'],[None]):
            with self.assertRaises(ValueError):validate_controls({'disabled_keys':bad})
        for value in (-1,257,1.5):
            with self.assertRaises(ValueError):validate_controls({'cpu_threads':value})

    def test_full_frame_preview_preserves_aspect_and_edges(self):
        rgb=np.zeros((600,1000,3),dtype=np.uint8);rgb[:,:100]=[255,0,0];rgb[:,-100:]=[0,0,255]
        result=Image.open(io.BytesIO(render_preview(rgb,[200,200,800,500],{},{})))
        self.assertEqual(result.size,(1000,600));self.assertGreater(result.getpixel((10,10))[0],240);self.assertGreater(result.getpixel((990,10))[2],240)

    def test_pipeline_disables_keys_and_debounces_txt_but_keeps_frame_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg={**DEFAULTS,'model_path':'models/faster_rcnn.onnx','device':'cpu','video_path':make_video(folder),'output_dir':folder,'disabled_keys':['Q'],'batch_size':4}
            job=Job('inference',cfg)
            # Boxes centered in Q and W, expressed relative to the default ROI.
            dets=np.array([[48,58,169,186,.99],[214,59,337,186,.99]])
            with patch('keyscope.backends.ONNXModel',return_value=Mock(batch_size=1,precision='FP32',setup_seconds=0,backend='cpu',device_name='CPU')),patch.object(engine,'predict',side_effect=lambda model,a,*args:[dets]*len(a)):
                engine.run_inference(job)
            lines=next(job.output.glob('*_keys.txt')).read_text('utf-8').splitlines()
            self.assertTrue(lines);self.assertTrue(all(line.split()[1]=='W' for line in lines))
            stamps=[float(line.split()[0]) for line in lines]
            self.assertEqual(stamps[0],0);self.assertTrue(all(b-a>.05 for a,b in zip(stamps,stamps[1:])))
            with next(job.output.glob('*_detections.csv')).open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),18);self.assertLess(len(lines),len(rows));self.assertEqual(job.effective_batch,1)


class ConversionTests(unittest.TestCase):
    def test_chords_dedup_and_bar_boundary(self):
        r=convert_score('0 D,Z\n0.03 D\n0.5 A,B\n0.53 A\n2 G\n',bpm=120,beats=4)
        self.assertEqual(r['events'],3);self.assertEqual(r['bars'],2)
        bars=r['text'].split('/');self.assertIn('(DZ)',bars[0]);self.assertIn('(AB)',bars[0]);self.assertEqual(bars[1],'G')

    def test_pauses_empty_bars_and_line_length(self):
        r=convert_score('0 Q\n0.25 W\n1 G\n4 H\n',bars_per_line=2)
        self.assertTrue(r['text'].startswith('QW'));self.assertIn(' G',r['text']);self.assertIn('/   /\n\nH/',r['text'])

    def test_pickup_is_retained_and_eighth_note_meter(self):
        r=convert_score('0 D\n1.5 G\n',bpm=120,beats=6,denominator=8,start=1.5)
        self.assertEqual(r['bars'],2);self.assertIn('D',r['text']);self.assertIn('G',r['text'])

    def test_distinct_close_notes_are_not_chords(self):
        r=convert_score('0 D\n0.03 G\n')
        self.assertIn('DG',r['text']);self.assertNotIn('(DG)',r['text'])

    def test_invalid_parameters_and_excessive_bars(self):
        for kw in ({'bpm':float('nan')},{'beats':1.5},{'denominator':3},{'bars_per_line':0},{'start':-1}):
            with self.assertRaises(ValueError):convert_score('0 G',**kw)
        with self.assertRaises(ValueError):convert_score('86400 G',bpm=400,beats=1)


if __name__=='__main__':unittest.main()
