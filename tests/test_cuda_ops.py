"""Numerical and batch-recovery checks for the optional PyTorch backend."""
import importlib.util
import unittest
from unittest.mock import patch
import numpy as np

HAS_TORCH=importlib.util.find_spec('torch') is not None
if HAS_TORCH:
    import torch
    from torchvision.ops import FrozenBatchNorm2d
    from keyscope.torch_ops import fuse_frozen_norms
    from keyscope.cuda_backend import predict


@unittest.skipUnless(HAS_TORCH,'CUDA dependencies are not installed')
class CUDAOpsTests(unittest.TestCase):
    def test_frozen_normalization_fusion_preserves_values(self):
        torch.manual_seed(9)
        model=torch.nn.Sequential(torch.nn.Conv2d(3,8,3,padding=1,bias=False),FrozenBatchNorm2d(8)).eval()
        bn=model[1];bn.weight.copy_(torch.randn(8));bn.bias.copy_(torch.randn(8))
        bn.running_mean.copy_(torch.randn(8));bn.running_var.copy_(torch.rand(8)+.2)
        data=torch.randn(3,3,17,29)
        with torch.inference_mode():
            expected=model(data);self.assertEqual(fuse_frozen_norms(model),1);actual=model(data)
        torch.testing.assert_close(actual,expected,rtol=2e-5,atol=2e-6)

    def test_oom_splitting_filters_labels_and_preserves_order(self):
        class Job:
            effective_batch=4
            def check(self):pass
            def log(self,message):pass
        class Model:
            def __call__(self,inputs):
                if len(inputs)>1:raise torch.cuda.OutOfMemoryError('Synthetic allocation failure')
                x=float(inputs[0][0,0,0])*255
                return [{'boxes':torch.tensor([[x,2,x+1,4],[5,6,7,8]]),'scores':torch.tensor([.9,.99]),'labels':torch.tensor([2,1])}]
        job=Job()
        with patch('torch.cuda.empty_cache'):
            rows=predict(Model(),[np.full((8,8,3),i,np.uint8) for i in range(4)],torch.device('cpu'),False,.8,job)
        self.assertEqual(job.effective_batch,1)
        np.testing.assert_allclose([row[0,0] for row in rows],range(4),atol=1e-5)
        self.assertTrue(all(row.shape==(1,5) for row in rows))

    def test_prefetched_batch_respects_reduced_limit_and_empty_results(self):
        sizes=[]
        class Job:
            effective_batch=2
            def check(self):pass
        class Model:
            def __call__(self,inputs):
                sizes.append(len(inputs))
                return [{'boxes':torch.zeros((0,4)),'scores':torch.zeros(0),'labels':torch.zeros(0,dtype=torch.long)} for _ in inputs]
        rows=predict(Model(),[np.zeros((8,8,3),np.uint8)]*5,torch.device('cpu'),False,.8,Job())
        self.assertEqual(sizes,[2,2,1]);self.assertEqual(len(rows),5)
        self.assertTrue(all(row.shape==(0,5) for row in rows))


if __name__=='__main__':unittest.main()
