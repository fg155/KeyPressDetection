# Key Press Detection

Convert Genshin Impact Windsong Lyre performance videos into timestamped scores by detecting the on-screen keys.

## Start

Extract the complete portable folder and run `start.cmd`. The browser opens a loopback address, normally `http://127.0.0.1:8765`; if occupied, subsequent ports are tried. Keep CMD open. Closing CMD ends the web service and inference. Closing the browser does not stop inference. The independent simulator remains open.

Python, PyAV, ONNX Runtime DirectML and inference models are included. No Python, pip, Node.js or CUDA installation is required. Use Windows 10/11 x64 with compatible graphics drivers. The source edition needs installation; see [README.md](README.md).

## Inference

1. Select a video and output directory. Load the preview to check the full frame.
2. Click keys to disable or enable recognition. Running jobs apply changes from the next processed batch.
3. Use **Move key regions** to move enabled boxes. Advanced parameters also offer drawing and coordinate inputs. **Reset positions** restores the original layout while retaining disabled keys. Save the layout for the next job.
4. Set confidence, batch size and frame stride, then start. Only one job runs at a time.

Defaults use 21 keys, reference size 1920x1080, ROI `[350,550,1550,1020]`, confidence 0.8 and model short side 800. Coordinates scale with video size; different layouts need calibration. Preview preserves the full frame and original aspect ratio.

Same-key debounce defaults to 50 ms from the last accepted timestamp. Repeats do not extend this window: detections at 0, 0.03, 0.05 and 0.06 seconds retain 0 and 0.06. Each key is independent. Zero disables debounce. TXT uses debounced results; CSV retains raw enabled-key samples.

TXT, CSV and the latest preview remain in memory until success. Stop discards incomplete results, including files written during finalization. Only job status and a short English log remain. Closing CMD loses unfinished in-memory results. Elapsed time advances through initialization and saving, then freezes when the job ends.

Each completed job has its own folder containing `<video>_keys.txt`, `<video>_detections.csv`, `<video>_key_events.csv`, `<video>_summary.json`, `preview.jpg`, `task.log` and `job.json`. Original video names, including Unicode, are preserved with invalid Windows characters replaced and the prefix capped at 100 characters. Timestamps start at the first frame, using PTS with an FPS fallback. Key intervals are inferred from samples, not hardware events.

Saved scores open directly through **Load in simulator**. Other files can be downloaded explicitly.

## Devices

The CUDA edition selects CUDA for NVIDIA checkpoints first, then DirectML, then CPU. The DirectML edition selects the compatible GPU with the most dedicated memory, then CPU. A specific GPU can be selected in Settings. DirectML defaults to FP32; FP16 mixed precision is optional. CPU always uses FP32. The page and English logs show the actual backend and precision.

DirectML defaults to batch 1. CUDA defaults to batch 16 and accepts batches up to 256. Batch 16 performs a real batched detector call and may improve dedicated-GPU throughput. The last short batch is padded and extra outputs are discarded. A failed batch 16 retries at batch 1; if DirectML still fails, the entire current batch is retried on CPU without duplicated score rows. CPU uses batch 1.

The CPU thread slider sets ONNX Runtime compute threads; 0 leaves selection to the runtime. GPU operators that DirectML cannot execute also use CPU. Larger batches or more threads do not always improve throughput. Lower resolution or frame skipping can miss notes.

Input short-edge settings (800/640/480) prepare a cached ONNX graph locally. First use includes model preparation and GPU compilation. The supplied base model, manifest, other graphs and shared `weights.data` must remain together. The CUDA edition also accepts PyTorch checkpoints and has AMP and TF32 settings. A custom checkpoint is exported to ONNX on its first DirectML or CPU run.

Separate model assets are available beside the portable packages in Releases. Extract the ONNX model ZIP into the application folder; CUDA users can also extract the matching PyTorch model ZIP. Select the base model in Settings. Model updates use these smaller downloads. The runtime stays installed.

## Simulator

Select a timestamped TXT or upload one, then open the independent simulator. Windows requests administrator access. `start-simulator.cmd` launches it without the web service.

Start playback and focus the game during the countdown. The button changes to Pause/Resume. F6 toggles start/pause/resume by default; F8 stops and resets. Both shortcuts can be changed in Settings and must use different keys. Changing foreground windows or holding a modifier pauses playback and releases keys. Return to the original game and press the toggle shortcut to resume. Returning focus alone does not resume. Resuming from the window button provides a countdown.

Merge gap defaults to **80 ms**, hold tail to 40 ms. Consecutive same-key samples within the gap merge; an explicit row without that key releases it. Tap mode treats each row as a chord. Speed scales timestamps and hold duration. TXT cannot recover exact release timing when empty frames were omitted.

Input is `seconds<TAB>Q,N`, using `QWERTYUASDFGHJZXCVBNM`. Supports UTF-8/BOM, UTF-16 with BOM and GB18030; up to 8 MiB, 200,000 timestamp rows and 24 hours. Blank lines and `#` comments are ignored. Leading silence is retained. Test without keyboard input: `runtime\python.exe simulator.py --dry-run`.

## Conversion and management

Conversion currently offers **Fingertip score**. Choose BPM, time signature, first-bar start and bars per line. Single notes become `G`, simultaneous chords `(DZ)`, and `/` ends a bar. Spaces show rests and improve layout without fixed duration. Empty and preceding bars are retained. Preview can be edited and downloaded as `<original>_formatted.txt`; the source is unchanged. The simulator requires timestamped TXT, not visual notation.

Score manager lists result folders under the selected directory. Search, select folders and click **Delete folders**. Confirmation removes all contents, including TXT, CSV, previews, logs and job metadata, and matching history entries. Running jobs are protected. Refresh if contents changed. Select a folder's parent to manage it. Uploaded scores have separate folders under `scores/`.

## Move the app

Copy the whole application folder. External videos/custom models must be copied separately and reselected if paths changed. Do not move the folder during simulator playback.

The language button switches Chinese/English without restarting jobs. Logs, implementation source and documentation are English; localization files retain Chinese translations. User filenames and saved data are not translated. Only inference is supported. TensorRT is not included.
