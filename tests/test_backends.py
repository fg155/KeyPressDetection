import builtins
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from keyscope import backends, config, edition, onnx_backend


class BackendTests(unittest.TestCase):
    def test_directml_profile_never_imports_torch(self):
        real_import=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.split('.')[0] in ('torch','torchvision'):raise AssertionError('Unexpected CUDA dependency import')
            return real_import(name,*args,**kwargs)
        with patch.object(backends,'cuda_enabled',return_value=False),patch('builtins.__import__',side_effect=guarded):
            self.assertFalse(backends.cuda_status()['available'])
            with patch.object(backends.hardware,'select_directml',return_value=None),patch.object(backends,'ONNXModel') as model:
                cfg={**config.DEFAULTS,'model_path':'models/faster_rcnn.onnx','device':'auto'}
                self.assertEqual(backends.create_model(cfg,Mock()),model.return_value)
                self.assertIsNone(model.call_args.args[2])

    def test_packaged_profile_overrides_installed_torch(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(edition,'ROOT',Path(temp)):
            file=Path(temp)/'edition.json';file.write_text('{"edition":"directml"}','utf-8')
            with patch.object(edition.importlib.util,'find_spec',side_effect=AssertionError('Profile must not inspect CUDA')):
                self.assertFalse(edition.cuda_enabled())
            file.write_text('{"edition":"cuda"}','utf-8');self.assertTrue(edition.cuda_enabled())
            file.write_text('{"edition":"invalid"}','utf-8')
            with self.assertRaises(ValueError):edition.profile()

    def test_cuda_checkpoint_has_priority_and_onnx_uses_directml(self):
        cfg={**config.DEFAULTS,'model_path':'model.pth','device':'auto'}
        fake=types.ModuleType('keyscope.cuda_backend');fake.CUDAModel=Mock()
        with patch.object(backends,'cuda_enabled',return_value=True),patch.object(backends,'cuda_status',return_value={'available':True}),patch.dict('sys.modules',{'keyscope.cuda_backend':fake}),patch.object(backends.hardware,'select_directml') as select:
            self.assertEqual(backends.create_model(cfg,Mock()),fake.CUDAModel.return_value);select.assert_not_called()
            with patch.object(backends,'ONNXModel') as onnx:
                backends.create_model({**cfg,'model_path':'model.onnx'},Mock())
                onnx.assert_called_once();self.assertEqual(fake.CUDAModel.call_count,1)

    def test_cuda_initialization_failure_falls_back_to_cpu(self):
        fake=types.ModuleType('keyscope.cuda_backend');fake.CUDAModel=Mock(side_effect=RuntimeError('driver failure'));fake.clear_model_cache=Mock()
        cfg={**config.DEFAULTS,'model_path':'model.pth','device':'cuda'}
        with patch.object(backends,'cuda_enabled',return_value=True),patch.object(backends,'cuda_status',return_value={'available':True}),patch.dict('sys.modules',{'keyscope.cuda_backend':fake}),patch.object(backends,'onnx_config',return_value={**cfg,'model_path':'model.onnx'}),patch.object(backends,'ONNXModel') as onnx:
            backends.create_model(cfg,Mock());self.assertIsNone(onnx.call_args.args[2])
            fake.clear_model_cache.assert_called_once()

    def test_checkpoint_bundle_requires_matching_model_and_weights(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'models';folder.mkdir()
            checkpoint=folder/'faster_rcnn.pth';checkpoint.write_bytes(b'checkpoint')
            graph=folder/'faster_rcnn.onnx';graph.write_bytes(b'graph')
            weights=folder/'weights.data';weights.write_bytes(b'weights')
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            info={'format':onnx_backend.FORMAT,'min_size':800,'batch_size':1,'precision':'fp32',
                  'source_sha256':sha(checkpoint),'onnx_sha256':sha(graph),'external_weights':'weights.data','external_weights_sha256':sha(weights)}
            Path(str(graph)+'.json').write_text(json.dumps(info),'utf-8')
            cfg={'model_path':str(checkpoint)}
            with patch.object(backends,'ROOT',root),patch.object(backends,'cuda_enabled',return_value=True):
                self.assertEqual(backends.onnx_config(cfg,Mock())['model_path'],str(graph))
                weights.write_bytes(b'changed')
                with patch('keyscope.onnx_export.export_model',side_effect=RuntimeError('export required')),self.assertRaisesRegex(RuntimeError,'export required'):
                    backends.onnx_config(cfg,Mock())

    def test_cuda_validation_accepts_large_batches_and_rejects_onnx_for_cuda(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(config,'cuda_enabled',return_value=True):
            root=Path(temp);(root/'model.pth').touch();(root/'model.onnx').touch();(root/'video.mp4').touch()
            cfg={'model_path':str(root/'model.pth'),'video_path':str(root/'video.mp4'),'device':'cuda'}
            self.assertEqual(config.validate_task('inference',{**cfg,'batch_size':64})['batch_size'],64)
            with self.assertRaises(ValueError):config.validate_task('inference',{**cfg,'model_path':str(root/'model.onnx')})


if __name__=='__main__':unittest.main()
