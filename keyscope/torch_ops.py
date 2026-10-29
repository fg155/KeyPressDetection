"""Inference-only optimizations; training and saved weights stay unmodified."""
import torch
from torch.nn.utils.fusion import fuse_conv_bn_weights
from torchvision.ops import FrozenBatchNorm2d
from torchvision.models.detection.transform import GeneralizedRCNNTransform


class ChannelsLastTransform(GeneralizedRCNNTransform):
    def batch_images(self, images, size_divisible=32):
        batch = super().batch_images(images, size_divisible)
        return batch.contiguous(memory_format=torch.channels_last)


def fuse_frozen_norms(module):
    """Fold ResNet's fixed affine normalization into its preceding convolution."""
    if module.training:
        raise ValueError('Normalization fusion requires evaluation mode.')
    count = 0
    for name, child in list(module.named_children()):
        if isinstance(child, FrozenBatchNorm2d):
            # ResNet uses conv1/bn1 etc., and Sequential(Conv, BN) in downsample.
            conv_name = 'conv' + name[2:] if name.startswith('bn') else str(int(name) - 1)
            conv = getattr(module, conv_name)
            if not isinstance(conv, torch.nn.Conv2d):
                raise TypeError('Expected a convolution before FrozenBatchNorm2d.')
            conv.weight, conv.bias = fuse_conv_bn_weights(
                conv.weight, conv.bias, child.running_mean, child.running_var,
                child.eps, child.weight, child.bias)
            setattr(module, name, torch.nn.Identity().eval())
            count += 1
        else:
            count += fuse_frozen_norms(child)
    return count


def optimize_inference_model(model):
    count = fuse_frozen_norms(model.backbone.body)
    old = model.transform
    model.transform = ChannelsLastTransform(
        old.min_size, old.max_size, old.image_mean, old.image_std,
        size_divisible=old.size_divisible, fixed_size=old.fixed_size).eval()
    model.to(memory_format=torch.channels_last)
    return count


# Kept for existing local profiling scripts.
optimize_cuda_model = optimize_inference_model
