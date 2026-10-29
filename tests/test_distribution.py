"""Distribution privacy and completeness boundaries."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
import zipfile
from tools import package_release as release


class DistributionTests(unittest.TestCase):
    def test_runtime_filter_keeps_libraries_and_licenses(self):
        for name in ('runtime/Lib/site-packages/torch/lib/torch_cuda.dll','runtime/python.exe','runtime/Lib/site-packages/onnxruntime/capi/onnxruntime.dll',
                     'runtime/Lib/site-packages/onnxruntime/capi/DirectML.dll',
                     'runtime/Lib/site-packages/onnxruntime_directml-1.23.0.dist-info/licenses/LICENSE',
                     'runtime/Lib/site-packages/numpy/testing/__init__.py'):
            self.assertTrue(release.runtime_needed(Path(name)),name)
        for name in ('runtime/Lib/site-packages/bin/torchrun.exe',
                     'runtime/Lib/site-packages/onnxruntime/transformers/torch_onnx_export_helper.py',
                     'runtime/Lib/site-packages/onnxruntime/quantization/quantize.py',
                     'runtime/Lib/site-packages/numpy/tests/test_example.py',
                     'runtime/Lib/site-packages/onnx/backend/test/data/model/input.pb',
                     'runtime/Lib/site-packages/onnx/test/test_example.py',
                     'runtime/Lib/site-packages/torch/include/torch.h',
                     'runtime/Lib/site-packages/example.dist-info/direct_url.json'):
            self.assertFalse(release.runtime_needed(Path(name)),name)

    def test_personal_path_rejection_preserves_existing_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.txt';target=root/'release.zip'
            target.write_bytes(b'previous release')
            source.write_text(str(root.resolve()),'utf-8')
            with self.assertRaisesRegex(ValueError,'Local identity/path'):
                release.build(target,'App',[source],root)
            self.assertEqual(target.read_bytes(),b'previous release')
            self.assertFalse(target.with_suffix('.zip.tmp').exists())

    def test_archive_metadata_is_normalized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.txt';source.write_text('public content','utf-8')
            target=root/'release.zip';release.build(target,'App',[source],root)
            with zipfile.ZipFile(target) as z:
                self.assertEqual(z.namelist(),['App/source.txt'])
                self.assertEqual(z.infolist()[0].date_time,(1980,1,1,0,0,0))
                self.assertEqual(z.read('App/source.txt'),b'public content')
            self.assertTrue(target.with_suffix('.sha256').is_file())

    def test_source_and_portable_are_separate_allowlists(self):
        source={p.relative_to(release.ROOT).as_posix() for p in release.source_files()}
        self.assertIn('tests/video_fixture.py',source)
        self.assertIn('tools/package_release.py',source)
        for name in ('PERFORMANCE.md','VALIDATION.md','examples/demo.mp4','settings.json',
                     'history.json','keyscope/data.py','models/faster_rcnn.pth'):
            self.assertNotIn(name,source)

    def model_inputs(self,root):
        models=root/'models';models.mkdir()
        for name in release.MODELS:
            if name.endswith('.json'):continue
            (models/name).write_bytes(name.encode())
        checkpoint=models/'faster_rcnn.pth';checkpoint.write_bytes(b'checkpoint')
        sha=lambda name:hashlib.sha256((models/name).read_bytes()).hexdigest()
        metadata={'format':'key-press-detection-onnx-v1','onnx_sha256':sha('faster_rcnn.onnx'),
                  'external_weights_sha256':sha('weights.data'),'source_sha256':sha('faster_rcnn.pth')}
        (models/'faster_rcnn.onnx.json').write_text(json.dumps(metadata),'utf-8')
        (models/'README.md').write_text('Public model instructions.','utf-8')
        return models,checkpoint

    def test_model_assets_are_independent_and_include_file_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);models,checkpoint=self.model_inputs(root)
            paths=release.model_archives(root/'dist',models,checkpoint,root=root)
            self.assertEqual(len(paths),2)
            for path in paths:
                self.assertEqual(path.parent,root/'dist')
                with zipfile.ZipFile(path) as z:
                    names=set(z.namelist())
                    self.assertTrue(all(n.startswith('models/') for n in names))
                    label='onnx' if 'ONNX.zip' in path.name else 'pytorch'
                    inventory=json.loads(z.read('models/'+label+'-package.json'))
                    for name,digest in inventory['files'].items():
                        self.assertEqual(hashlib.sha256(z.read('models/'+name)).hexdigest(),digest)
                    if label=='onnx':
                        self.assertNotIn('models/faster_rcnn.pth',names)
                        self.assertTrue({'models/'+name for name in release.MODELS}<=names)
                    else:self.assertEqual(names,{'models/faster_rcnn.pth','models/README.md','models/pytorch-package.json'})

    def test_mismatched_model_pair_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);models,checkpoint=self.model_inputs(root)
            checkpoint.write_bytes(b'other checkpoint')
            with self.assertRaisesRegex(ValueError,'must match'):
                release.model_archives(root/'dist',models,checkpoint,root=root)
            self.assertFalse((root/'dist').exists())

    def test_pytorch_asset_does_not_require_an_onnx_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);models=root/'models';models.mkdir()
            checkpoint=root/'new.pt';checkpoint.write_bytes(b'new checkpoint')
            (models/'README.md').write_text('Model instructions.','utf-8')
            paths=release.model_archives(root/'dist',models,checkpoint,'pytorch','FasterRCNN-v2',root)
            self.assertEqual(paths[0].name,'KeyPressDetection-Model-FasterRCNN-v2-PyTorch.zip')
            with self.assertRaises(ValueError):release.model_archives(root/'dist',models,checkpoint,'pytorch','../bad',root)


if __name__=='__main__':unittest.main()
