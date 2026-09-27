# Current approach

This summary records the approach as of 2026-09-27. It distinguishes implemented
prototype behavior from the intended product workflow and proposed next work.
See [design](PROJECT_DESIGN.md) for the product specification,
[anchor tracking](ANCHOR_TRACKING.md) for algorithm details, and
[project plan](PROJECT_PLAN.md) for verifiable development steps.

## Goal and tradeoffs

Turn action footage into a smoothly following, leveled view of a user-selected
subject. Keep the full timeline initially; the user chooses interesting sections
later. The sailing example follows the other boat, including its sail, hull and
sailor, excluding the camera boat. The same design should support skiing and
open-ocean sailing with scene-appropriate orientation evidence.

- Strong zoom and a blurry subject are acceptable. Identity and visible subject
  coverage matter more than sharpness.
- Smooth framing takes priority over reacting immediately to each detection.
  Offline processing and lookahead are acceptable.
- Preserve as much of the subject as the original contains. Allow the viewport
  outside the source, feathering its edges into a blurred extension. This does
  not recover missing scene content.
- Briefly hold framing on uncertain tracking, then widen and seek new evidence.
  Keep uncertain intervals visible for human review.
- Use Qwen liberally, but separate identity, location, motion reliability and
  leveling evidence. A confident description does not prove a correct box.
- Analysis FPS is configurable and separate from output FPS. A 10 FPS default
  is not a claim that any particular 10 FPS experiment has finished. Discovery
  scanning in anchor mode defaults to 2 FPS.

## Tracking: expand from trusted anchors

The implemented anchor mode replaces the requirement for a complete first
forward pass. Existing single and dual traversal modes remain available; projects
must explicitly select the desired mode.

1. Seed from the initial subject selection and saved human labels. Human boxes
   are authoritative anchors; explicit human absence is also preserved.
2. Propagate forward and backward using CPU Lucas–Kanade optical flow through
   intervening source frames. At scheduled analysis positions, validate the
   predicted, relaxed crop with Qwen.
3. Relocalize within the search region when motion is unreliable or the relaxed
   region becomes too large. Crop validation establishes identity inside a
   region; it does not establish tight object boundaries.
4. Promote newly localized, verified and complete detections above the anchor
   threshold. A high score on a propagated crop alone cannot create an anchor.
5. When propagation stalls, independently scan unresolved positions that have
   not had a full-frame scan at the discovery cadence. New qualifying detections
   restart bidirectional expansion. Stop when no eligible work remains.

Relaxation uses predicted motion plus uncertainty, not an unconditional 10%
expansion at every frame. Current defaults add 15% per side with an 8-pixel
minimum; dimension growth beyond 1.5× or area growth beyond 2× the last localized
box triggers localization. Work attempts are bounded to prevent endless retries.
These are experimental parameters, not physical guarantees.

## Two detection paths and confidence

At an independent detection step, retain both candidates:

| Path | Qwen input | Saved geometry |
|---|---|---|
| Raw / cyan | Original frame, rotation angle and temporal context | Original-space box/polygon |
| Leveled / orange | Rotated frame and temporal context | Inverse-mapped original-space polygon and enclosing rectangle |

Coordinates are canonical in the original image. The UI's orange rectangle is
the enclosing source-space rectangle; it is distinct from the inverse-mapped
quadrilateral. Both candidates and the selected result remain inspectable.
Selection considers verified evidence, completeness, consistency and ambiguity;
it is not an unconditional per-frame maximum of detector self-confidence.

Qwen supplies a box note, but a note is not proof that it examined the proposed
pixels. Code crops the actual box, obtains a blind crop description, and compares
that description with trusted target text. The resulting semantic identity-match
score supplies tracking confidence. Detector self-confidence and other notes
remain diagnostics. Missing identity evidence is not treated as a successful
match. Completeness is evaluated separately and can trigger localization retries.
Blur is explicitly acceptable when coarse identity features remain sufficient.

The acceptance threshold defaults to 50%; the separate high-confidence anchor
threshold defaults to 85%. Both are adjustable in the UI. Scores are heuristic
reliability measures, not calibrated probabilities. Optical-flow motion quality
is a separate quantity and never becomes human-level identity certainty.

Temporal image history starts with the five most recent frames. Older moderate
or high-confidence frames top up the reliable evidence, then older high-confidence
frames top up strong evidence, with at most 15 selected history frames. Favorable
history may need only five. Human target crops provide identity references;
additional crop attachments are not additional historical frame positions.
Full audit history is saved even though only bounded context reaches Qwen.

## Leveling and rendering

For supported DJI telemetry, gyro mode uses decoded fused-attitude roll for the
final rotation. Independent Qwen visual leveling is retained for comparison and
flags divergence. It receives the current image and line candidates, without
previous angles or telemetry, to avoid anchoring its answer to those values.
The inspected DJI axis mapping remains provisional; this is not a universal
camera adapter. Missing or invalid telemetry fails gyro mode explicitly.

Visual leveling is available for gyro-free footage. Camera roll, shoreline
perspective, terrain slope and subject lean must remain distinct. Open ocean may
provide a horizon; a shoreline or ski slope is not automatically horizontal.

Rendering combines selected tracking, leveling and smooth crop/zoom trajectories
at source cadence. Unsampled positions can use interpolated/held geometry; the
UI does not describe those positions as fresh Qwen detections. Saving a correction
and rendering it does not require rerunning Qwen; propagating its tracking effect
requires analysis.

## Review and human authority

The focus page displays the original frame alongside a leveled/zoomed preview.
A rectangle drawn on either view is saved as an original-space polygon, with
its preview transform and enclosing box. Polygon masks constrain human reference
crops and optical-flow feature initialization. Selections outside all source
content are rejected; decorative borders are not source evidence.

Shared Frame Analysis contains **Approve Cyan (raw path)** and **Approve Orange
(leveled path)**. Either is enabled whenever that path has a displayed box,
including zero-confidence, held and interpolated estimates. Approval saves the
exact displayed outline at the displayed frame. It does not silently approve a
neighboring sample instead.

Drawing and approval update the same project's `corrections.json`; they do not
create a new project or launch processing. An approved/drawn box has human
confidence 100%, overrides automatic evidence at that frame, skips detection
there on a subsequent pass, and becomes an anchor and eligible reference. That
certainty does not transfer to neighboring frames. Original model predictions
remain available; users may replace a label or mark the target absent.

The comparison page plays original and processed panels on one synchronized
encoded timeline. Cyan/orange show candidate estimates, while dashed green shows
the saved render track. Frame Analysis names human, independent-detection,
flow-validation or interpolation provenance. Detailed model analysis belongs to
the exact displayed frame; neighboring sample details are not substituted.
Navigation jumps between reviewed frames, sampled frames and flagged intervals.

## Labels saved during a running job

**Implemented:** the UI and backend allow approvals and manual corrections during
processing. Settings changes and starting another managed job remain blocked.
Labels are saved immediately and shown as human evidence.

**Current limitation:** analysis loads manual labels at pass initialization. An
already running pass is not guaranteed to consume a later edit. Reanalyze or
render afterward to guarantee its application; do not assume saving already
updated the running worker's history or queue.

**Proposed, not implemented:** check the label revision before each analysis task
and before publishing its result. Reload only on change, let human labels win
against in-flight results, update reference/cache revisions, and queue affected
forward/backward work. Retain unrelated work and debounce repeated edits.
Replacing or removing labels must also retire affected anchor descendants.
The file check/read is inexpensive and needs no GPU. The substantial potential
cost is additional Qwen verification/localization during propagation.

## Intended three-part product workflow

| Part | User activity | Offline system work | Status |
|---|---|---|---|
| Design | Pick videos, give instructions, select representative frames and subject; iterate on a plan | Qwen drafts a structured plan; optional Codex/Claude reviews plan and evidence | Product design; planner/reviewer integration remains future work |
| Validate | Review trial quality and revise or approve each plan | Queue trial runs for videos with designed plans; surface failures and disagreements | Current per-project analysis/review supplies building blocks; batch approval workflow remains future work |
| Produce | Review completed output and select interesting segments | Process videos with approved plans, render and retain diagnostics | Current rendering/comparison exists; durable batch production and segment selection/export workflow remain future work |

The repository uses a dedicated Python environment, portable project settings,
configurable model endpoints and ignored local media/output directories. The
current service manages one processing job; durable worker coordination, robust
job lifecycle recovery and immutable run/plan versions are still development work.
