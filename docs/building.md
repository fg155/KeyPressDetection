# Building releases

The repository produces a source ZIP, two portable editions and separate model ZIPs. All Release assets go into the same output directory. Python files, the web interface and documentation are shared. The packager selects dependencies and model files, then writes `edition.json` with the edition and source fingerprint.

Use Python 3.12 x64. The portable runtime input is a `runtime` folder containing Python, Tcl/Tk and the packages in the matching lockfile. An existing portable release provides this folder.

## Inputs

| Input | CUDA | DirectML |
| --- | --- | --- |
| Runtime packages | `requirements-cuda.lock.txt` | `requirements-directml.lock.txt` |
| ONNX models | All files in the shared `models` bundle | Same bundle |
| PyTorch checkpoint | Matching `faster_rcnn.pth` | Omitted |

The ONNX manifest records `source_sha256`, `onnx_sha256` and `external_weights_sha256`. The CUDA checkpoint must match the recorded source hash. Keep the four ONNX graphs and `weights.data` together.

The runtime input may contain extra packages. Packaging copies the locked distributions and filters development files, package tests and caches. A DirectML build from a CUDA runtime still excludes PyTorch and CUDA libraries.

## Commands

From the repository root:

```bat
python tools/package_release.py --kind source --output dist

python tools/package_release.py --kind models --model-format both --models C:\build\models --checkpoint C:\build\faster_rcnn.pth --output dist

python tools/package_release.py --kind portable --edition directml --runtime C:\build\runtime-directml --models C:\build\models --output dist

python tools/package_release.py --kind portable --edition cuda --runtime C:\build\runtime-cuda --models C:\build\models --checkpoint C:\build\faster_rcnn.pth --output dist --split
```

Replace the input paths with your build folders. The CUDA checkpoint can also live in the model folder; in that case, omit `--checkpoint`. When the portable ZIP is at least 2 GiB, `--split` creates download parts, a `.parts.json` manifest and a single `join-release.cmd` script. Keep these files together. Double-click the script to merge and verify the ZIP.

`--kind models` packages weights without a runtime. Choose `--model-format onnx`, `pytorch` or `both`. `--model-name` changes the asset label for a model version; its default is `FasterRCNN`. When packaging both formats, the ONNX manifest must match the checkpoint hash. This command packages existing model files. The application supports Faster R-CNN checkpoints and its exported ONNX format.

Output:

```text
dist/
  KeyPressDetection-Source.zip
  KeyPressDetection-CUDA-Windows-x64-Portable.zip
  KeyPressDetection-CUDA-Windows-x64-Portable.zip.part001
  KeyPressDetection-CUDA-Windows-x64-Portable.zip.part002
  KeyPressDetection-CUDA-Windows-x64-Portable.zip.parts.json
  join-release.cmd
  KeyPressDetection-DirectML-Windows-x64-Portable.zip
  KeyPressDetection-Model-FasterRCNN-ONNX.zip
  KeyPressDetection-Model-FasterRCNN-PyTorch.zip
```

Each ZIP has a SHA256 sidecar. Model ZIPs contain a `models/` folder and an inventory of individual file hashes. Both portable packages record the same source fingerprint when built from the same checkout. Upload this repository once and attach the portable and model downloads to the Release. A model update can publish just its new model assets.

README media lives in `docs/media/` and is included in source and portable archives. Check UID redaction before replacing the demo files.

## Checks

```bat
python -B -m unittest discover -s tests
node tests/test_frontend.js
```

CUDA-specific tests run when PyTorch is installed. Test each portable build after extracting it into a new folder. Check inference, precision selection, CPU fallback and simulator launch with that folder's runtime.
