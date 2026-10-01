# Discovery and verification model comparison

Run separately from production analysis using the guarded model-swap runner in
`../leveling/run_models.py`. The plan accepts `benchmark_script`, `report_script`,
and `benchmark_timeout` overrides. Production units and settings are unchanged.

## Tasks and controls

- Independent discovery: production prompt and schema, one held-out target reference
  and one current frame, no optical/history context, no crop-verification retries.
  Raw frames for all clips; expanded gyro-leveled images where gyro exists.
  Query frames are at least 16 frames from their reference. Human boxes/absence are
  evaluation labels only. Full frames are resized to a maximum 1280 pixels for requests.
- Blind crop observation: exact production prompt, no target text or reference image.
  Positive crops come from human boxes, negative images from human absent labels.
- End-to-end crop verification: each model's crop description compared to the approved
  identity using the production text-comparison prompt. Additional cross-target negatives
  pair a green-sail crop with a white-sail identity, or the reverse.
- Fixed text-only comparison: controlled positive, blurry, partial, wrong-color,
  camera-relative, background, and wrong-category descriptions identical for all models.

Same runtime, quantization configuration, serial concurrency, temperature zero, and
thinking-disabled request flag for all candidates. Production output budgets (650
for detection, 1000 for description/comparison) and truncation retries apply equally.
Measure wall latency including retries, request counts, token usage, schema errors,
detection IoU against human boxes, absent-frame false positives, and identity decisions
at 0.5. Also retain raw responses, crops, and visual overlays for manual inspection.
Identity confidence is not an accuracy ground truth. Human-labeled positive crops are
not guaranteed perfect boxes. Text descriptions need visual auditing; schema validity
alone does not measure description fidelity. This is a small sailing-specific test,
not evidence about skiing or general-purpose vision.

## Commands

```
python experiments/discovery/benchmark.py prepare --spec SPEC.json --output DATASET
python experiments/discovery/benchmark.py run --manifest DATASET/manifest.json \
  --output RESULTS --endpoint http://127.0.0.1:8001/v1 --model SERVED_MODEL
python experiments/discovery/report.py RESULTS/results.json --output report.html
```

SPEC lists clips with name, config, corrections, and optional gyro file paths. Artifacts,
weights, and machine-specific plans belong outside the repository. Model swapping must
use both the runner's finally restoration and systemd ExecStopPost restoration guard.
