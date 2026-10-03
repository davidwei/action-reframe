# Standalone video leveling

This system turns one constant-frame-rate video and a maximum processing-time budget
into a versioned, per-frame leveling annotation. It does not import action-reframing
tracking or rendering code, and it does not create a rendered video.

The default operating design is:

1. Decode independently resumable 60-second chunks and retain original frame numbers.
2. Sample visual references across the full playback timeline. A long slow-motion file
   uses playback seconds: its high capture rate does not multiply the model call rate.
3. Use a fast primary visual model to select horizons or shoreline evidence. Code derives
   the signed angle from line coordinates.
4. Estimate relative background rotation at 5 FPS with optical flow. Weak, localized,
   or decode-gap motion is not treated as support.
5. Add primary-model samples around inconsistent intervals, then use a second review
   model on the remaining difficult frames.
6. Solve the angle timeline from absolute visual anchors and relative motion. Frames too
   far from usable evidence, damaged decode intervals, and model disagreements are flagged.
7. Write immutable JSONL shards plus a checksummed manifest and a static evidence report.

## Output contract

`leveling.json` uses schema `video-leveling-annotations/v1`. Each JSONL row contains:

```json
{
  "frame": 123,
  "time_seconds": 4.1041,
  "correction_degrees_ccw": 7.2,
  "evidence_quality": 0.54,
  "source": "visual_and_background_motion",
  "flags": []
}
```

Positive correction angles use the OpenCV convention: rotate the raw image
counterclockwise by that amount. `evidence_quality` is an uncalibrated support score,
not a probability of physical correctness. A null angle is intentional and must not be
silently replaced with zero by consumers.

Other files include `review_intervals.json`, `timeline_preview.json`, `state.json`,
checksummed annotation shards, model requests, sampled images, and `report.html`.

## Selecting models

The tool separates primary and review models. With an already running OpenAI-compatible
server:

```bash
python -m standalone.video_leveling.cli primary \
  --video VIDEO --output OUTPUT --hours 6 \
  --primary-model SERVED_MODEL --review-model REVIEW_MODEL \
  --api-url http://127.0.0.1:8001/v1
```

For automatic local model swapping, copy `model_catalog.example.json` into a machine-local
plan and set `primary.path`, `primary.served_name`, `review.path`, and
`review.served_name`. The orchestrator validates the exact served model ID. A changed
model requires a new output directory, preventing cached evidence from different models
from being mixed.

The guarded orchestrator processes all videos with the primary model before loading the
review model. Run it under a transient systemd unit with an independent `ExecStopPost`
that restarts the production model service. It also restores and verifies production in
its own `finally` block.

The optional `pause_services` plan field lists user services that depend on production
inference. Only services found active are stopped, and those same services are restarted
after production inference has passed its exact-model readiness check.

For a multi-day run, generate and enable a persistent user service. It starts again
after a reboot and resumes from checksummed artifacts:

```bash
python -m standalone.video_leveling.make_service \
  /path/to/plan.json /path/to/action-video-leveling.service
systemctl --user link /path/to/action-video-leveling.service
systemctl --user enable --now action-video-leveling.service
```

The unit restarts after abnormal termination without retrying permanent input errors
forever. Its stop hook restores the production model and services named in the plan.

## Time budget

`--hours` is a maximum charged processing budget for one video. It is distributed across
decode preparation (10%), primary visual calls (40%), optical motion passes (30%),
primary refinement (7.5%), review-model calls (7.5%), and export (5%).
The tool may finish earlier. It saves after each chunk or model call and resumes without
repeating valid work. Increasing only the budget is supported; changing input, algorithms,
sampling settings, or model identities requires a new output directory.

The first version supports CFR input. Timestamp gaps and corrupt frames retain their
source indices and become unknown/flagged annotations. VFR input is rejected because an
integer frame index alone would be ambiguous for downstream consumers.
