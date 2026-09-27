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

### Comparing raw and leveled tracking

Set `tracking_mode` to `dual` in a project config and use a separate `output_dir`.
The current implementation requires supported, frame-aligned DJI attitude telemetry;
it fails explicitly if that telemetry is unavailable. `analysis_fps` controls both
paths. At 2 FPS, the previous frame hint means the previous **sample**, about 0.5 s
away, not the immediately preceding playback frame.

* `raw_angle`: Qwen receives the unrotated frame, current gyro-derived roll, target
  reference, previous box hint and directional temporal context.
* `leveled`: the current frame is rotated using its own gyro-derived roll on an
  expanded canvas. A separate copy shows the previous source box projected through
  the current rotation. Qwen returns a box in the expanded image; all four corners
  are inverse-transformed into original source pixels. The source polygon and its
  clipped enclosing rectangle are both saved. Rectangle round trips can inflate
  boxes; the polygon makes that difference inspectable.

Both paths receive clean and hint images, retain separate histories and caches,
and run their own backward recovery pass. All historical images and historical
box coordinates remain explicitly labeled as raw source coordinates. Neither path
sees the other path's predictions. Analysis records every sample; the renderer
interpolates between samples as before. Color-based recovery/refinement is disabled
in dual mode so that it does not confound the comparison.

Artifacts: `tracking_raw_angle_forward.json`, `tracking_leveled_forward.json`,
`tracking_raw_angle.json`, `tracking_leveled.json`, each path's backward report,
and `tracking_comparison.json` (paired results with source-coordinate box IoU).
Request audits include prompts, transforms, previous hint frame, model response,
confidence, and mapped polygon. Resume with `--stage analyze`; cached successful
requests are reused. The legacy standalone `--stage backward` is rejected in dual
mode to avoid accidentally mixing the two algorithms.

`tracking_render_path` selects `raw_angle` (default) or `leveled`. Run `--stage render`
after changing it. The review comparison shows both sampled boxes on an original
frame: cyan raw+angle, orange leveled, dashed orange inverse-mapped polygon. Its
sample timestamp is explicit; it is not a new model detection on every playback frame.

### Compact tracking history

Tracking requests now start with the last five visited samples. If fewer than five
selected samples have confidence >= 0.65, the nearest older qualifying samples are
added until that quota is met. Then the nearest older samples with confidence >=
0.85 are added until five selected samples meet the high-confidence quota. A high
confidence sample also satisfies the moderate-or-high quota. Only visible/partial
observations with a box and no error qualify. Missing recent samples still remain
in the recent set to show motion/loss context. Traversal order is respected in both
forward and backward passes, and each dual path selects from its own predictions.

This uses 5–15 automatic history images once five prior samples exist (possibly
fewer at startup or when no qualifying observations exist). Identical frames are
included once. The original user-selected target crop remains an identity reference;
optional `reference_frames` in the project config lists additional zero-based source
frame indices that are always included as identity references, even when temporally
later than the current frame. These explicit references are additional to the 15-frame
history limit and are deduplicated against selected history frames.

`temporal_context.recent_images` defaults to 5; `moderate_images` and `high_images`
are **quotas within the selected set**, each defaulting to 5, rather than independent
buckets. `moderate_confidence` and `high_confidence` default to 0.65 and 0.85.
Only selected history records are sent as text; the complete history is still saved
in each request's `history.json`. Request audits record selected frame IDs and which
quota added each frame. If the token budget is exceeded, image resolution decreases
without silently dropping selected frames. Old broad-history settings
`history_visual_frames` and `history_char_budget` no longer drive tracking selection.

### Paired inference and selected tracking

Dual tracking now submits the two independent requests concurrently for each sampled
source timestamp. Both must finish before the next timestamp starts. Histories remain
independent; selection and adjudication never overwrite either path's observations.
Backward recovery also runs independently for the two paths, followed by chronological
reselection so recovered candidates can affect the final output.

The default `tracking_render_path` is now `selected` (existing explicit `raw_angle` or
`leveled` configs still force that path). `tracking_selected_forward.json` preserves the
initial decisions; `tracking_selected.json` stores the decisions after recovery. Each
`tracking_comparison.json` entry includes both candidates and a `selected` record with
path, reason, flags, switch marker, overlap and any adjudication response/audit.

Selection defaults in `tracking_selection`:

* Reliable candidate: valid visible/partial box, confidence >= 0.65, no model error or
  scene-cut signal.
* Agreement: box IoU >= 0.35. Keep the active path unless the challenger has a confidence
  advantage of at least 0.15 for three consecutive samples (1.5 s at 2 FPS).
* One reliable candidate: use it if motion-consistent.
* Confident disagreement or an abrupt position jump: ask Qwen to compare both labeled
  candidates against the target reference, clean current raw frame and selected-track
  history. A verified choice must have confidence >= 0.65. Otherwise select neither.
* Continuity gate: source-normalized center displacement <= 50 + 1000 * elapsed seconds;
  applied only within 2 seconds of the previous selected detection. This is a configurable
  image-motion heuristic, not a physical acceleration limit. Review flags remain even
  when adjudication accepts a candidate.

When neither is selected, the existing hold-then-widen camera planner applies. Switching
between otherwise plausible agreeing candidates uses hysteresis; an adjudicated choice
or failure of the active path can switch immediately. Between analysis samples, boxes
are interpolated and the crop is smoothed. Per-playback-frame provenance labels mixed-path
interpolation explicitly with contributing sample frames and paths. Candidate confidence
and adjudication confidence remain model-reported, not calibrated probabilities.

The UI highlights the selected candidate with a thicker outline, displays both confidences
and the selection reason, and adds jump buttons for switches and selection-review flags.
Individual malformed candidate responses are retained as errors and do not abort the run;
three consecutive samples with errors from both paths stop processing for service review.

During synchronized comparison playback, the original (left) panel always overlays
available dual-path candidates: cyan polygon for raw+angle and orange source-coordinate
rectangle for the leveled path. These include uncertain/rejected candidates; selection
remains separately recorded. Boxes interpolate only between adjacent available samples
within 1.5 configured sample intervals. Missing neighboring observations and longer gaps
are not bridged. The overlay is a review aid and is not burned into exported videos.

### Box notes and crop-grounded confidence

Dual forward and backward proposals now include `box_note`, describing contents inside
the final proposed coordinates after a self-check. Coordinate instructions explicitly
specify top-left origin, right/down axes and full-image normalization, including padding;
previous-box hint coordinates use the same normalized convention.

With `verify_boxes: true` (default for dual tracking), code crops the exact clean image
Qwen measured: raw for the raw path, expanded rotated image for the leveled path. The
crop uses outward integer rounding and is saved losslessly. First, a separate image
request describes that crop with the target reference but **without the proposal note,
history or confidence**. Then a text-only request compares the independent description
with `box_note`, recording semantic consistency and specific discrepancies.

Both original `model_confidence` and adjusted `confidence` are retained. Adjusted confidence
is the minimum of original confidence, crop-verifier confidence and note/description
consistency. Target absent => 0. Apparently incomplete target => cap at 0.64 (below the
0.65 acceptance threshold). Missing notes or verifier errors => 0. This is a conservative
heuristic, not a calibrated probability. Agreement alone cannot raise the original score.
The crop alone cannot prove that all target parts outside its edges are included, so
completeness remains an imperfect model assessment.

Adjusted confidence drives history quotas, backward recovery eligibility and path selection.
All candidate boxes remain available as diagnostic overlays even when verification rejects
them. The analysis panel reports `box_note`, independent crop description, presence and
completeness, discrepancies, original confidence and adjusted confidence. Request/response
files and crop PNGs live under each path's `box_verification` cache directory. Verification
adds two requests per non-null proposal; successful checks are cached.

### Extended backward tracking and direction selection

Dual tracking now revisits confident forward samples as well as uncertain ones. Starting
from the latest reliable forward anchor, each reverse chain continues as long as its own
crop-verified predictions remain reliable. A frame where forward wins does not stop that
chain: subsequent reverse requests keep the backward estimate in their motion history.
An unreliable backward result ends the chain; an earlier reliable forward observation can
seed another chain. Explicit user labels remain authoritative and reset propagation.

For each raw/leveled path separately:

* Agreeing valid candidates: strictly higher verified confidence wins, with **no margin**;
  an exact tie keeps forward.
* Only one reliable direction: keep it.
* Both reliable but IoU below `tracking_selection.agreement_iou` (default 0.35): adjudicate
  the two labeled candidates against current pixels and reference. Unresolved disagreement
  produces an uncertain sample and stops that reverse chain.

Both original candidates, their verification records, overlap and adjudication are saved
in `direction_comparison`; `direction_choice` and `direction_reason` record the decision.
`tracking_<path>_directions.json` provides a separate audit, and each path has a backward
progress file and report distinguishing newly recovered samples from improved confident
forward samples. The UI displays forward/backward boxes and verified scores for inspection.
The raw-versus-leveled selector then runs over these direction-selected results, followed
by camera-path smoothing. Its existing cross-path switching hysteresis is separate from
the no-margin forward/backward comparison. Legacy single-path gap recovery is unchanged.

### Human-confirmed tracking anchors

In an existing project, draw a rectangle on the original source frame and use
**Save target box**. This saves one authoritative label in the project's
`output_dir/corrections.json`, keyed by zero-based source frame number, with
`bbox: [left, top, right, bottom]` in original source pixels. Saving again at the
same frame replaces that label. No project is created and no processing starts.
The original video remains the image source; a separate reference-image copy is
not necessary. Initial project creation remains available when no project exists.

On reanalysis, manual frames are inserted into the sample schedule even when
between regular analysis samples. Their boxes are normalized for model context,
marked `manual: true`, `confidence_source: human`, and assigned confidence 1.
Single-path and both dual-path forward analyses skip detection at those frames;
backward analysis preserves them, and cross-path selection skips adjudication.
They therefore also bypass crop verification. Manual absence remains a separate
explicit label with no box and zero target confidence.

Manual target frames participate in the same directional history quotas as model
observations: five recent frames, then qualifying older frames to reach five
moderate-or-high and five high-confidence observations, without duplicates. They
are not appended as unconditional references or counted outside the 15-frame
budget. Forward traversal uses earlier frames; backward uses later frames.
Reliable manual anchors retain already visited backward history. Human confidence
is an instruction, not a calibrated model probability.

Reanalyze and render to propagate a new label through tracking. Rendering saved
analysis applies corrections to framing but does not update model tracking.
The review UI shows the saved label immediately; existing rendered output remains
unchanged until regenerated. The service currently blocks saving while its managed
processing job is running.

### Clean detection inputs and verification retries (dual tracking v4)

Both dual-tracking paths, in both traversal directions, now locate the target in a
clean full frame without the yellow previous-box overlay or numerical previous
boxes. Detection history keeps the same frame/confidence selection quotas but
omits bounding boxes and free-form old notes (which could repeat coordinates).
History full-frame images still provide motion context. This does not introduce
an expanded search crop or change the source-coordinate conversion.

For each selected historical human target label, context also attaches an exact
PNG crop from its original source frame, labeled as an identity reference rather
than a current-location hint. It counts as the same historical frame for quota
selection, but is an additional image attachment. The audit records
`manual_crop_frames` and `attached_image_count`; the original full frame remains.

A proposal below the confidence threshold after successful crop verification
triggers a retry, up to `box_verification_retries` (default 2, allowed 0–2).
The retry receives the clean full frame, the rejected crop explicitly labeled as
such, and the independent verifier's findings. It must search the full frame
again and return full-frame coordinates. It receives neither the rejected box
coordinates nor the previous proposal response. Every new proposal is verified.
A null box, request/verification error, accepted proposal, or exhausted retry
budget ends the loop. Final low confidence remains uncertain; retries never
promote an unverified proposal. Manual anchors still bypass this entire process.

All attempts, responses, confidence adjustments, and request-file paths are
retained under `detection_attempts`; the UI shows the retry count for each path.
Per-attempt cache directories prevent request audits from overwriting one another.
The dual cache namespace is bumped to v4, so new analyses do not reuse v3 results.
Existing running processes and previously rendered videos are not modified.
