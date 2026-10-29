# Dependencies

Portable releases include Python 3.12 x64, Tcl/Tk, PyAV, NumPy, Pillow, ONNX and ONNX Runtime DirectML. The CUDA package adds PyTorch, Torchvision and CUDA libraries. The packager selects exact distributions from the edition's lockfile.

For source use, run `install.cmd directml` or `install.cmd cuda`. Packages install into `.venv`; `edition.json` records the selected profile.

Download wheels on Windows x64 for an offline installation:

```bat
py -3.12 -m pip download -r requirements-directml.txt -d dependencies\wheels
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-index --find-links dependencies\wheels -r requirements-directml.lock.txt
```

For CUDA, use `requirements-cuda.txt` for downloading and `requirements-cuda.lock.txt` for offline installation. Extract the matching model assets from Releases into the application folder. Graphics drivers are installed through Windows or the GPU vendor.
