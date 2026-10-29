"""Routing, real-batch output handling, thread settings and recovery contracts."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
from keyscope import config, engine, hardware, onnx_backend as backend
from keyscope.jobs import Job, Cancelled
from video_fixture import make_video

NVIDIA = {'id':0,'name':'NVIDIA test GPU','vendor_id':0x10de,'dedicated_bytes':16,'directml_capable':True}
AMD = {**NVIDIA,'id':2,'name':'AMD test GPU','vendor_id':0x1002,'dedicated_bytes':8}
INTEL = {**NVIDIA,'id':1,'name':'Intel test GPU','vendor_id':0x8086,'dedicated_bytes':1}
META = {'format':backend.FORMAT,'batch_size':1,'precision':'fp32','min_size':800,
        'variants':{'fp32_16':'batch16.onnx','fp16_mixed_1':'mixed.onnx','fp16_mixed_16':'batch16_mixed.onnx'}}


class ONNXTests(unittest.TestCase):
    def make_model(self, batch=16, adapter=NVIDIA, precision='fp16_mixed'):
        cfg={**config.DEFAULTS,'batch_size':batch,'directml_precision':precision}
        with patch.object(backend,'metadata',return_value=META):
            return backend.ONNXModel(cfg,Mock(),adapter)

    def tearDown(self):
        backend.clear_session()

    def test_vendor_routing_excludes_software_and_unsupported_devices(self):
        software={**NVIDIA,'vendor_id':0x1414}
        with patch.object(hardware,'adapters',return_value=[INTEL,AMD,NVIDIA,software,{**AMD,'directml_capable':False}]):
            self.assertEqual(hardware.directml_adapters(),[INTEL,AMD,NVIDIA])
        with patch.object(hardware,'directml_status',return_value={'adapters':[INTEL,AMD,NVIDIA]}):
            self.assertEqual(hardware.select_directml(),NVIDIA)
            self.assertEqual(hardware.select_directml(1),INTEL)
            self.assertEqual(hardware.select_directml(2),AMD)
            self.assertIsNone(hardware.select_directml(9))

    def test_cpu_forces_fp32_batch_one(self):
        model=self.make_model(adapter=None)
        self.assertEqual(model.precision,'FP32');self.assertEqual(model.batch_size,1)

    def test_model_without_batch16_variant_uses_batch_one(self):
        with patch.object(backend,'metadata',return_value={**META,'variants':{}}):
            model=backend.ONNXModel({**config.DEFAULTS,'batch_size':16},Mock(),NVIDIA)
        self.assertEqual(model.batch_size,1)

    def test_real_batch_padding_output_positions_and_threshold(self):
        model=self.make_model();session=Mock();seen=[]
        def run(_,feeds):
            x=feeds['images'];seen.append(x.copy())
            result=[]
            for row in x:
                value=float(row[0,0,0])*255
                result.extend([np.array([[value,0,value+1,1],[99,0,100,1],[98,0,99,1]]),np.array([.9,.7,.99]),np.array([2,2,1])])
            return result
        session.run.side_effect=run
        arrays=[np.full((4,5,3),i,dtype=np.uint8) for i in range(19)]
        with patch.object(model,'_session',return_value=session):
            output=model.predict_arrays(arrays,.8)
        self.assertEqual([a.shape for a in seen],[(16,3,4,5)]*2)
        np.testing.assert_allclose([x[0,0] for x in output],range(19),atol=1e-5)
        self.assertTrue(all(x.shape==(1,5) for x in output))
        np.testing.assert_array_equal(seen[1][2],seen[1][-1])

    def test_gpu_batch_failure_retries_remaining_frames_at_one(self):
        model=self.make_model();calls=[]
        def run(arrays,threshold):
            calls.append((model.batch_size,len(arrays)))
            if model.batch_size==16:raise RuntimeError('Insufficient memory')
            return [np.array([[int(a[0,0,0]),0,1,1,.9]]) for a in arrays]
        with patch.object(model,'_predict_chunk',side_effect=run):
            rows=model.predict_arrays([np.full((2,2,3),i,dtype=np.uint8) for i in range(3)],.8)
        self.assertEqual(calls,[(16,3),(1,1),(1,1),(1,1)])
        self.assertEqual([x[0,0] for x in rows],[0,1,2])
        self.assertEqual(model.job.effective_batch,1)

    def test_cancel_does_not_trigger_backend_retries(self):
        model=self.make_model()
        with patch.object(model,'_predict_chunk',side_effect=Cancelled),self.assertRaises(Cancelled):
            model.predict_arrays([np.zeros((2,2,3),np.uint8)],.8)
        self.assertEqual(model.batch_size,16)

    def test_cpu_errors_are_not_reported_as_gpu_failures(self):
        model=self.make_model(adapter=None)
        with patch.object(model,'_predict_chunk',side_effect=ValueError('bad graph')),self.assertRaisesRegex(ValueError,'bad graph'):
            model.predict_arrays([np.zeros((2,2,3),np.uint8)],.8)

    def test_session_providers_threads_and_implicit_fallback_rejected(self):
        import onnxruntime as ort
        for adapter,threads,expected in [(None,0,0),(0,6,6),(1,99,24)]:
            with patch.object(ort,'InferenceSession') as create,patch('os.cpu_count',return_value=24):
                create.return_value.get_providers.return_value=['DmlExecutionProvider','CPUExecutionProvider']
                backend.create_session('model.onnx',470,1200,adapter,threads)
                kwargs=create.call_args.kwargs;options=kwargs['sess_options']
                self.assertEqual(options.intra_op_num_threads,expected)
                if adapter is None:self.assertEqual(kwargs['providers'],['CPUExecutionProvider'])
                else:
                    self.assertEqual(kwargs['providers'][0],('DmlExecutionProvider',{'device_id':adapter}))
                    self.assertFalse(options.enable_mem_pattern)
        with patch.object(ort,'InferenceSession') as create:
            create.return_value.get_providers.return_value=['CPUExecutionProvider']
            with self.assertRaises(backend.DirectMLFailure):backend.create_session('model.onnx',470,1200,0)

    def test_manifest_rejects_wrong_format_and_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'base.onnx';sidecar=Path(str(path)+'.json')
            with self.assertRaises(ValueError):backend.metadata(path)
            sidecar.write_text(json.dumps({**META,'batch_size':16}),'utf-8')
            with self.assertRaises(ValueError):backend.metadata(path)
            sidecar.write_text(json.dumps(META),'utf-8')
            self.assertEqual(backend.metadata(path),META)
            with self.assertRaises(ValueError):backend.variant_path(path,{'variants':{'fp32_16':'../escape.onnx'}},'fp32',16)

    @patch('keyscope.config.cuda_enabled',return_value=False)
    def test_validates_only_supported_devices_and_batches(self, _enabled):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'model.onnx').touch();(root/'clip.mp4').touch()
            cfg={'model_path':str(root/'model.onnx'),'video_path':str(root/'clip.mp4'),'output_dir':str(root/'runs')}
            for batch in (1,16):self.assertEqual(config.validate_task('inference',{**cfg,'batch_size':batch})['batch_size'],batch)
            for batch in (0,2,32,1.5):
                with self.assertRaises(ValueError):config.validate_task('inference',{**cfg,'batch_size':batch})
            with self.assertRaises(ValueError):config.validate_task('inference',{**cfg,'device':'cuda'})

    def test_gpu_failure_retries_entire_batch_on_cpu_without_duplicate_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg={**copy.deepcopy(config.DEFAULTS),'model_path':'models/faster_rcnn.onnx','video_path':make_video(temp),'output_dir':temp,'batch_size':16,'directml_precision':'fp16_mixed'}
            job=Job('inference',cfg);gpu=Mock(batch_size=16,precision='FP16 mixed',setup_seconds=0,backend='directml',device_name='NVIDIA test GPU')
            cpu=Mock(batch_size=1,precision='FP32',setup_seconds=0,backend='cpu',device_name='CPU')
            gpu.predict_arrays.side_effect=backend.DirectMLFailure('Test driver failure')
            cpu.predict_arrays.side_effect=lambda arrays,threshold:[np.array([[48,58,169,186,.99]]) for _ in arrays]
            with patch.object(hardware,'select_directml',return_value=NVIDIA),patch('keyscope.backends.ONNXModel',side_effect=[gpu,cpu]):
                engine.run_inference(job)
            with next(job.output.glob('*_detections.csv')).open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual([int(r['frame']) for r in rows],list(range(18)))
            self.assertEqual(job.state['metrics']['device'],'cpu')
            self.assertEqual(job.state['metrics']['precision'],'FP32')
            self.assertEqual(len(cpu.predict_arrays.call_args_list[0].args[0]),16)


if __name__=='__main__':unittest.main()
