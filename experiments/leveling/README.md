# Isolated leveling experiments

This harness calls the existing visual-leveling implementation without modifying production configuration, services, project results, or stage caches. All experiment outputs belong in a separate directory.

## Protocol

1. Prepare a fixed dataset from a JSON specification: `{"clips":[{"name":"clip","video":"/path/video.MP4","times":[0,10,20],"gyro":"/optional/gyro.json"}]}`. Omit `gyro` for clips without telemetry.
2. Use `benchmark.py prepare --spec SPEC --output DATASET` with the project environment. Images are resized to 1280 pixels wide.
3. Run `benchmark.py run --manifest DATASET/manifest.json --output RUN --endpoint URL/v1 --model EXACT_MODEL_ID`. Use a different output directory for each model/repetition. Cached observations are identified and excluded from fresh-request timing.
4. Generate an inspectable report with `report.py RUN/results.json --output RUN/report.html`.

Requests are serial, use the production two-image prompt and line candidates, temperature zero, a 400-token output budget, and explicitly disable thinking. Report token-limit failures as failures rather than silently changing the budget for one model. Record model revisions and runtime versions separately. The first request is included; larger follow-up tests should distinguish warm-up and steady-state latency.

Compare reference-line placement, abstention and invalid-output rates, gyro disagreement, and request latency. Model-reported confidence is not accuracy. The current gyro mapping is provisional; disagreement is not a calibrated angular-error measurement. A shoreline's apparent slope is not necessarily gravity. Human reference annotations and controlled rotations are useful follow-up tests, but are not included in this first dataset.

## Production isolation

Never stop or reconfigure a production model merely because the queue is idle. An idle vLLM server can still reserve all GPU memory. Obtain an explicit maintenance window before temporarily replacing it, or use separate hardware/CPU. Keep the experimental runtime separate from the production environment. Restore and verify the exact production model before ending any maintenance window. Do not compare CPU candidate speed to the GPU baseline as if it measured relative model efficiency.

The initial dataset contains 12 frames from two sailing videos: three slow-motion frames without gyro and nine frames with saved gyro. This is a smoke benchmark, not a comprehensive comparison across skiing, open-ocean horizons, or other scene types.
