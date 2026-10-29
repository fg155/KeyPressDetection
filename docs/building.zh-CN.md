# 打包

同一份源码生成源码 ZIP、两个便携版和独立模型包，所有 Release 附件放在同一输出目录。Python 代码、网页和文档共用，打包时选择依赖及模型文件，并生成记录版本类型和源码指纹的 `edition.json`。

使用 Python 3.12 x64。运行库输入为包含 Python、Tcl/Tk 和对应锁定依赖的 `runtime` 文件夹，可以从现有便携包中取得。

## 输入文件

| 输入 | CUDA | DirectML |
| --- | --- | --- |
| 依赖清单 | `requirements-cuda.lock.txt` | `requirements-directml.lock.txt` |
| ONNX 模型 | 共享 `models` 文件夹中的所有文件 | 相同模型 |
| PyTorch 权重 | 配套的 `faster_rcnn.pth` | 不包含 |

ONNX 清单记录 `source_sha256`、`onnx_sha256` 和 `external_weights_sha256`。CUDA 权重必须匹配记录的源文件哈希。四个 ONNX 文件与 `weights.data` 放在同一目录。

打包器只收集依赖清单中的包，并排除开发文件、测试数据和缓存。即使用 CUDA 运行库作为输入，DirectML 包也会排除 PyTorch 和 CUDA 库。

## 命令

在项目根目录运行：

```bat
python tools/package_release.py --kind source --output dist

python tools/package_release.py --kind models --model-format both --models C:\build\models --checkpoint C:\build\faster_rcnn.pth --output dist

python tools/package_release.py --kind portable --edition directml --runtime C:\build\runtime-directml --models C:\build\models --output dist

python tools/package_release.py --kind portable --edition cuda --runtime C:\build\runtime-cuda --models C:\build\models --checkpoint C:\build\faster_rcnn.pth --output dist --split
```

将输入路径换成实际目录。权重放在模型目录中时，可以省略 `--checkpoint`。便携 ZIP 达到 2 GiB 时，`--split` 会生成分卷、`.parts.json` 清单和单个 `join-release.cmd` 脚本。将这些文件放在同一文件夹，双击脚本即可合并并校验 ZIP。

`--kind models` 只打包模型，`--model-format` 可选 `onnx`、`pytorch` 或 `both`。用 `--model-name` 指定模型版本的附件名称，默认是 `FasterRCNN`。同时打包两种格式时，ONNX 清单必须匹配权重哈希。这个命令打包已有模型文件，应用支持 Faster R-CNN 权重及其导出的 ONNX 格式。

输出文件：

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

每个 ZIP 都附带 SHA256 文件。模型包包含 `models/` 文件夹及各模型文件的哈希清单。同一源码构建的两个便携包记录相同的源码指纹。GitHub 上传一份源码，将便携包和模型包一起放进 Release；后续更新模型时，可以只发布新的模型附件。

README 的演示素材放在 `docs/media/`，源码包和便携包都会收录。更换素材前检查 UID 遮挡。

## 检查

```bat
python -B -m unittest discover -s tests
node tests/test_frontend.js
```

安装 PyTorch 后会运行 CUDA 专用测试。便携包解压到新目录后，使用包内运行库检查推理、精度切换、CPU 兜底和模拟器启动。
