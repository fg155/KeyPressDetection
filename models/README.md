# Models

Download model assets from the same Release as the application:

| Asset | Contents |
| --- | --- |
| `KeyPressDetection-Model-FasterRCNN-ONNX.zip` | Four ONNX graphs, their manifest and shared weights |
| `KeyPressDetection-Model-FasterRCNN-PyTorch.zip` | The PyTorch checkpoint for CUDA |

Extract into the application folder and merge `models/`. Select the base `.onnx` file or `.pth` checkpoint in Settings. A source installation uses these same model assets. Updating both matching assets keeps CUDA and its DirectML/CPU fallback on the same weights.

Each model ZIP has a SHA256 sidecar. The JSON package inventory inside it lists individual model file hashes.

The DirectML edition starts with `faster_rcnn.onnx`. Its manifest selects FP32 or mixed FP16, at batch 1 or 16. Keep all four graphs and `weights.data` together. The graphs share weights without changing their values.

The CUDA edition also includes `faster_rcnn.pth` and uses it by default. Its ONNX manifest records the checkpoint SHA256, base graph SHA256 and external weights SHA256. This links CUDA inference to the same model used by DirectML and CPU fallback. Custom checkpoints export into the local cache on their first ONNX run.

The model is Faster R-CNN ResNet-50 FPN with fixed normalization folded into convolution weights. Class 2 is a pressed key. ONNX input is float32 RGB NCHW in [0,1], with dynamic height and width. Preprocessing and box-coordinate restoration are inside the graph. The default short edge is 800 and the maximum long edge is 1333.

Mixed FP16 uses half precision for neural compute blocks. Preprocessing, box calculations, ROI alignment, score normalization and NMS retain FP32. CPU uses the FP32 graph. Short-edge changes prepare a cached graph locally.

Portable releases include these models. Model-only ZIPs provide separate downloads; source archives include the model instructions.
