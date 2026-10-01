# Local visual-leveling model experiment — 2026-10-01

The common-budget smoke test favors **Qwen3.8-27B-FP8 as the most reliable drop-in candidate for the current prompt and consistency checks**. Gemma 4 is faster and produces the same computed angles on the nine gyro-backed samples, but usually contradicts those angles in its direction field. This experiment does not establish calibrated gravity accuracy or justify an automatic production model replacement.

## Dataset and protocol

- Twelve 1280-pixel-wide images from two sailing videos: three slow-motion frames at approximately 0, 10, and 20 seconds without gyro, and nine frames at approximately 0, 5, 10, 20, 30, 40, 44.51, 50, and 55.02 seconds with saved gyro estimates.
- Existing `leveling.visual_observation` prompt: original image plus an annotated copy containing measured line candidates. The model selects a candidate or supplies normalized endpoints. Code calculates the image-line angle.
- Identical prompt, serial requests, temperature zero, thinking explicitly disabled, 400 output tokens. Cached model observations were not reused.
- Two RTX 5090 GPUs, tensor parallelism 2, vLLM 0.30.0, PyTorch 2.13.0+cu130, Transformers 5.18.0, eager mode, 8192-token context. The existing production weights were also served in this environment as the control.
- Qwen models use official FP8 checkpoints; Gemma uses official instruction-tuned weights with online FP8 quantization. These are measurements of this serving configuration, not each model's maximum optimized throughput.
- Startup is recorded separately. Median request latency reduces the influence of first-use kernel compilation; means include it. This is one small run, without confidence intervals or a broad distribution of scenes.

## Common-budget results

| Model | Median request latency | Mean request latency | Passed consistency checks | Truncated outputs | Mean gyro disagreement, all nine frames |
|---|---:|---:|---:|---:|---:|
| Current Qwen3-VL-32B-FP8, experimental runtime | 3.79 s | 6.37 s | 7/12 | 0 | 2.42° |
| Qwen3.8-27B-FP8 | 4.64 s | 4.70 s | 12/12 | 0 | 2.03° |
| Qwen3.6-35B-A3B-FP8 | 13.32 s | 12.00 s | 1/12 | 10 | Not available |
| Gemma 4 31B instruction-tuned, online FP8 | 2.40 s | 2.47 s | 2/12 | 0 | 2.03° |

“Passed” means a parsed angle, nonzero orientation confidence, and no contradiction detected between the angle and the direction field. It is **not a human-verified accuracy rate**. The saved gyro axis mapping is provisional rather than calibrated ground truth. A shoreline is not necessarily horizontal in perspective. Gyro disagreement is therefore a diagnostic, not an absolute accuracy measurement.

Qwen3.6 often emitted a long prose explanation before the requested JSON. Ten responses exhausted 400 tokens. This was ordinary answer content, not a hidden reasoning field. Those failures must not be interpreted as ten wrong angle estimates: the complete estimates were unavailable.

The control's first request took about 34.7 seconds including first-use overhead; subsequent requests were much faster. Its original production-runtime measurement was 5.72 seconds mean, with six of twelve outputs passing consistency checks. Kernel/runtime changes can affect both speed and exact output, which is why the same-runtime control is retained separately.

## Higher-budget Qwen3.6 diagnostic

A separately labeled repeat used the same images and prompt with a 1,200-token budget. It returned 11 complete outputs, passed consistency checks on 10/12 frames, and still truncated one response. Median request latency was **15.70 seconds**, mean **16.29 seconds**. Mean gyro disagreement was **2.80° over eight available frames**; Qwen3.8 was **2.02° on those same eight frames**. The larger budget improves completion reliability but does not establish a quality or efficiency advantage. Its latency must not be presented as a same-budget result.

## Visual inspection and practical interpretation

The reference-line overlays were inspected for all twelve images:

- At slow-motion 0 seconds, the control selected a foreground boom segment. Qwen3.8 rejected that segment and provided a more plausible background line, though it still called the reference a sea-sky horizon despite visible land.
- At slow-motion 10 seconds, Qwen3.8 selected the visible shoreline segment. Gemma's freely generated line underestimates the apparent slope; Qwen3.6 returned a horizontal line.
- At 44.51 seconds in the gyro-backed clip, the control selected a line through the water (15.79°), while Qwen3.8 and Gemma selected the shoreline (12.00°). Saved gyro is 12.14°. This single sample accounts for the difference in mean gyro disagreement: the other eight computed angles match across these three models.
- At approximately 20 seconds in the gyro-backed clip, the common selected line lies in the water below the shoreline. A small gyro disagreement does not prove correct visual grounding.
- At 55.02 seconds, the three models' computed line angle is -20.52° while saved gyro is -28.59°. None eliminates this discrepancy. Shoreline shape, camera geometry, and the provisional telemetry mapping need investigation before assigning blame exclusively to a model.

Qwen3.8 is the best **current-prompt integration** candidate. Gemma deserves a follow-up where direction is derived from measured endpoints and reference placement is checked independently; its contradictory direction text masks otherwise comparable computed angles. Do not silently remove the production consistency safeguard based on this small experiment.

## Reproducibility and isolation

Pinned repositories:

- `Qwen/Qwen3.8-27B-FP8`: `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`
- `Qwen/Qwen3.6-35B-A3B-FP8`: `95a723d08a9490559dae23d0cff1d9466213d989`
- `google/gemma-4-31B-it`: `842da3794eaa0b77d5f08bae87a17459d91ff475`

The experiment uses a separate environment and model directory. No production model files, service configuration, or project analysis results are changed. The experimental API is on a separate port, so production clients cannot accidentally use a candidate. A controller `finally` and a systemd `ExecStopPost` guard restore the original production service.

Initial launch failures were runtime setup problems and are excluded from capability measurements. The new runtime initially found an old system compiler; then pip-selected CUDA 13.4 compiler components conflicted with PyTorch's CUDA 13.0 headers. The isolated environment pins NVCC, CRT, NVVM, and NVJitLink to 13.0.88. A CUDA compilation check passed before the successful benchmark.

The reusable harness lives in [experiments/leveling](../experiments/leveling/README.md). Local experiment artifacts are under the workspace's `outputs/experiments/leveling-models/`: pinned downloads and full dependency freeze, `runs_final/index.html`, individual visual reports, raw model responses, GPU samples, startup logs, and restoration records. Dataset images and the source manifest are under `outputs/diagnostics/leveling_models_20261001/dataset/`. Paths are supplied through plans and CLI arguments; machine-specific paths are not embedded in the harness.

## Final restoration

The original production service was restored after both the main benchmark and the extended diagnostic. The final `/v1/models` check returned the original `Qwen3-VL-32B-FP8` model, and a live inference smoke request returned `READY` with finish reason `stop`. The recorded production context limit remains 32,768 tokens. Experimental model weights and the separate runtime remain available for future tests.
