# Video focus prototype

Offline object-focused reframing with a local Qwen3-VL endpoint, reviewable observations, per-frame crop/roll data, and a synchronized original/processed comparison.

## Environment

Use a dedicated Python 3.12 environment and install the repository requirements as described in [README](../README.md). No particular Conda environment or local service name is assumed. Configure your own compatible Qwen endpoint with `QWEN_API_URL` or project `api_url`.

FFmpeg is supplied by `imageio-ffmpeg`; PyAV inspects metadata. This guide describes prototype behavior. Named sailboat results below are historical examples and are not distributed with the repository.

## Watch and compare

```bash
./scripts/run_review.sh
```

Open <http://127.0.0.1:8765/compare> for the example comparison, or <http://127.0.0.1:8765/> for selection and correction tools.

The comparison combines the original on the left and processed result on the right into **one encoded video**. They share timestamps, playback speed, seeking and audio; two independent players cannot drift because there is only one playback timeline. Each panel is displayed at 960×540. The original video is unchanged.

- Play/pause, speed 0.25×–2×, frame stepping, and ±5-second jumps.
- Space plays/pauses; arrow keys step; Shift+arrow keys jump five seconds when controls are not focused.
- Review buttons jump to flagged intervals.
- Reload latest render after rerendering a project.
- Both pages include a frame-analysis text panel: rendered box/center/size, leveling angle, crop/zoom, review flags, visibility, model notes, and confidence indicators. The comparison panel follows playback and seeking; the selection page follows the displayed source frame. Expand “All stored values (JSON)” for the complete track, neighboring observations, and saved corrections.
- Confidence is model-reported for the explicitly labeled nearest sampled Qwen frame, not a calibrated score for every intervening frame. Lost or uncertain tracks have a separate status badge. Saved manual corrections are shown separately from rendered values.

Browser seeking/frame display depends on the browser decoder; synchronization of the two panels is guaranteed by their shared encoded frame.

## Process the example

The historical target and preferences are illustrated in `configs/sailboat_example.json` and [DECISIONS.md](DECISIONS.md). Create your own workspace project through the UI; the commands below use its configuration path.

```bash
./scripts/run_reframe.sh path/to/project.json --stage all
./scripts/run_reframe.sh path/to/project.json --stage analyze
./scripts/run_reframe.sh path/to/project.json --stage backward
./scripts/run_reframe.sh path/to/project.json --stage render
./scripts/run_reframe.sh path/to/project.json --stage compare
```

Analysis uses the configured compatible vision endpoint. The default is `http://127.0.0.1:8000/v1`; there is no assumption that a local model service has been installed. Endpoint requirements and overrides are documented in [README](../README.md).

Analysis automatically includes one backward recovery pass (`backward_recovery: true`, enabled by default). For each run of uncertain observations followed by a confident observation, it starts at that right-hand detection and works backward through the run. Each accepted result becomes the seed for the next earlier sample. Qwen compares the original identity reference, the later confirmed crop, and an enlarged earlier search region located with optical-flow camera-motion estimation. Confidence must meet the same 0.65 threshold as first-pass tracking; it is never increased merely because a later detection exists.

The chain stops at the first failed/uncertain step, a scene-cut report, or a manual absent label. A trailing gap with no later confident detection is skipped. Previously confident observations are not replaced. The pass operates at the configured analysis FPS (10 FPS by default); the renderer still estimates intervening frames. It does not guarantee recovery through occlusion or a target leaving the source image.

For this green-sail example, `target_hue: 43` selects the sail color in OpenCV's 0–179 hue scale. Backward recovery asks Qwen to choose among numbered color components, then uses measured component bounds with padding for the hull/sailor. This avoids both model coordinate errors on enlarged crops and accidentally treating blue sky/water in the reference rectangle as the target color. This specialization is disabled for newly created general-subject projects.

`--stage backward` reruns only this pass from the preserved first-pass snapshot, with content-keyed caching of individual attempts. Then run `--stage render` to update both videos. Normal `--stage all` does analysis, backward recovery and rendering automatically. The frame-analysis panel labels backward results and shows their seeds, evidence and before/after confidence.

The review page can select another video, load a timestamp, draw a target rectangle, and create a separate project. Supply an unambiguous target description. For example, explicitly distinguish a separate boat from the camera boat.

After analysis, draw corrections at specific frames, mark absence, or add roll keyframes. Render again to apply saved corrections. Rectangle corrections are pixel coordinates in the original video; positive roll means a line slopes downward toward the right in the source image. Manual roll keyframes adjust the visual roll curve and are interpolated between keyframes.

## Saved outputs

In `outputs/sailboat_example/`:

- `focused.mp4`: reframed preview, original audio copied.
- `comparison.mp4`: synchronized side-by-side comparison, audio once.
- `observations.json`: VL detections, visibility and visual leveling estimates.
- `observations_first_pass.json`: original first-pass observations, preserved before backward recovery.
- `backward_report.json`: intervals, seed frames, attempted/recovered samples and stopping reasons.
- `tracks.json`: every frame's box, crop center, crop height, roll and review flags.
- `review_flags.json`: timestamped flagged intervals.
- `corrections.json`: user edits, separate from model responses.
- `source_metadata.json`: container/stream metadata inspection.
- `cache/`: reference, sampled frames and individual model responses for resumption.

## Current limitations

This is a first-pass prototype, not a validated general-purpose tracker. Qwen examines samples at the configured analysis FPS. Between them, geometry is interpolated; the example also enables sail-color refinement gated by VL location. New projects disable that specialized refinement. Tiny recovery candidates require nearby temporal confirmation before acceptance. A dedicated video tracker remains a next improvement for arbitrary subjects and abrupt motion.

Leveling is a visual shoreline estimate, not decoded IMU/gravity data. Shoreline perspective and inaccurate VL coordinates can cause residual tilt. The review interface supports correction keyframes. Actual box/identity errors may also survive automated confidence checks: flags are heuristics, not guarantees.

The supplied example is constant-frame-rate 29.97 fps. The current renderer uses a constant output frame rate; variable-frame-rate sources and slow-motion timing need additional validation before general use. Cuts are not automatically detected yet.

The output is an 8-bit H.264 review preview; the input is 10-bit HEVC. HDR/color-managed mastering is not implemented. Blurred extensions contain stretched image-edge colors, not reconstructed scene detail. Source-clipped portions of a sail cannot be recovered.

No quality filtering or trimming is applied. Uncertain or absent portions are retained, with a brief hold followed by widening. Strong digital zoom is permitted.

## Checks

```bash
./scripts/test.sh
```

The geometry checks cover target containment under rotation, missing-target widening, roll sign, and filling source-exterior regions.

## Analysis FPS experiments

The selection/review page has an **Analysis FPS** field and Save button. The next Analyze or Analyze + render job uses that value. The default is 10 FPS (one observation approximately every 0.1 seconds); output playback stays at the source rate, 29.97 FPS for this clip. Valid rates are positive and no greater than the source FPS. Existing projects using `sample_interval` remain supported.

Keep experiments separate with:

```bash
./scripts/run_reframe.sh path/to/project.json --analysis-fps 5 --output-dir outputs/experiment_fps5 --stage all
./scripts/run_reframe.sh path/to/project.json --analysis-fps 10 --output-dir outputs/experiment_fps10 --stage all
```

Each run saves `run_config.json`, the actual rate in `meta.json`, and progress in `analysis_progress.json`. To review an experiment, open `/compare?config=outputs/experiment_fps5/run_config.json`. Changing the rate invalidates analysis caches. Saving a setting does not regenerate an existing video; rendering alone uses the observations' original sampling rate.

Forward Qwen requests now carry earlier analysis results; backward requests carry later observations in reverse traversal order, including accepted recoveries. Context includes target geometry/confidence and signed leveling estimates, recent images, and older contact sheets. Full history is saved under `cache/.../context/`; older records and images are summarized/subsampled to fit the model context window. Request audits record exactly what was sent, omitted, summarized, and the token count. History is evidence, not a constraint: current images can override earlier mistakes. Sequential forward processing is necessary for this context and can take substantially longer at higher FPS.

The original development workspace had a 2 FPS baseline in `outputs/sailboat_example`; those videos are not included in a checkout. Higher sampling density and temporal context do not guarantee correct shoreline leveling.
