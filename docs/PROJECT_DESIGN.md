# Action video reframing: project design

The [architecture and next steps](ARCHITECTURE_ROADMAP.md) define the agreed four core components, video-level scheduling, folder-level workflow, and separate feature-building and optimization tracks.

See [current approach](CURRENT_APPROACH.md) for the implemented tracking/review behavior, agreed tradeoffs, and the boundary between current functionality and planned work.

Design agreed through discussion on 2026-09-26. This document describes the intended product; the implementation boundary is listed below. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the staged implementation and acceptance checks, and [prototype guide](PROTOTYPE.md) for current commands.

## 1. Goal

Build an offline video-processing tool that acts as a virtual camera operator. A user selects a subject and describes the desired result. The system follows the subject, estimates camera orientation, and creates smoothly framed, leveled footage with automatic zoom. The user later selects interesting sections for export.

The initial example is `dji_mimo_20260821_154414_20260822064414_1787971455825_video.MP4`. The target is the other lime-green-sailed dinghy, including its sail, hull, and sailor, excluding the camera boat and foreground rigging.

The product should generalize to coastal sailing, open-ocean sailing, skiing, and other action footage. Camera roll, terrain slope, and subject lean are different quantities. Leveling must not flatten a ski slope, force a perspective shoreline horizontal, or remove a subject's natural lean.

Success means that the intended subject remains identifiable and as fully visible as the source permits, camera movement is comfortable to watch, orientation corrections have supporting evidence, and failures are easy to find and correct. Smooth motion or a high model confidence score alone does not establish correctness.

## 2. Agreed tradeoffs

| Area | Decision | Implication |
|---|---|---|
| Zoom | Strong digital zoom and blur are acceptable | Prioritize subject visibility; do not discard footage just because it is soft |
| Subject coverage | Preserve as much of the visible subject as possible | Include relevant equipment; permit the viewport to extend outside the source |
| Borders | Feather into a blurred, extended background | Decorative fill, not reconstructed scene content |
| Following | Prefer smooth framing and zoom | Some lag is acceptable; offline lookahead can reduce lag |
| Leveling | Correct camera roll while preserving the subject | Use evidence appropriate to the scene; flag ambiguous orientation |
| Missing subject | Briefly hold course, then widen | Reidentify with Qwen; do not silently switch identity |
| Uncertainty | Flag uncertain tracking and leveling separately | Concentrate user corrections on difficult intervals |
| Automation | Automatic first, targeted corrections afterward | Do not require manual labels for every frame |
| Recovery | Make one backward recovery pass from later confident detections | Extend confidence only when new evidence supports it |
| Context | Supply directional temporal history in both passes | Save full history; summarize/subsample older context within model limits |
| Speed | Offline processing; latency is acceptable | Support unattended, resumable batches and future-frame evidence |
| Analysis FPS | Configurable; current experiment is 10 FPS | Sampling rate is independent of output playback rate |
| Footage selection | Preserve the full timeline initially | Choose interesting segments after viewing transformed footage |
| Environment | Dedicated project environment | Do not use the LeRobot Conda environment |

Current adjustable defaults, not fixed product requirements: 1280×720 review output, subject approximately 55% of output height, 0.75-second hold, and widening over 2 seconds. The example source/output cadence is approximately 29.97 FPS.

Do not use a universal human g-force limit as a hard pixel-motion bound. Image motion also depends on camera rotation, depth, lens projection, and platform movement. Use image-space consistency and soft trajectory constraints instead.

## 3. Three-part workflow

The workflow deliberately separates interactive preparation from two potentially slow offline batch runs. Each video progresses independently; a project library groups many videos.

### Part 1 — Design plans

1. Import videos and apply shared preferences where appropriate.
2. For each video, write the desired outcome, such as “Follow this boat smoothly and keep the camera level.”
3. Select a clear subject reference. Optionally add frames showing other appearances, useful orientation cues, or desired composition.
4. The system supplements user references with distributed scene samples and short sequences, including difficult conditions where possible.
5. Qwen proposes a structured plan tied to evidence in those references.
6. A configurable second reviewer, Codex or Claude, critiques the evidence and plan. Prefer an independent assessment of the evidence before revealing Qwen's conclusions.
7. The application checks the plan against supported operations and actual available data. The user iterates through plain-language feedback.
8. Select **Queue for trial** when the plan is ready to test.

Keep this part responsive by using limited evidence rather than full-rate video analysis. Model calls can run asynchronously with saved drafts. “Ready for trial” is not approval for full processing.

### Part 2 — Offline trials, then plan approval

1. Select **Run trials** for all eligible videos.
2. Offline workers analyze and render representative intervals using each queued plan version.
3. Trial coverage includes user-selected moments, distributed samples, and difficult intervals. The interface shows tested and untested areas; interval boundaries include enough context for tracking and smoothing.
4. On return, the user reviews synchronized original/processed results, quality flags, and the exact plan/settings used.
5. For each video, approve the plan, revise and queue another trial, correct references, or set the video aside.

Approval means “the strategy performed acceptably on these tested intervals,” not “every frame has been verified.” Revisions create new versions. Previous results remain available. Reuse compatible cached work, but never mix evidence from incompatible plans or settings.

### Part 3 — Offline full production, then selection

1. Select **Process approved videos**. Only approved, unchanged plan versions are eligible.
2. Offline workers perform full analysis, backward recovery, orientation estimation, trajectory smoothing, rendering, and quality checks.
3. The user returns to a final-review inbox, inspects flagged problems, and marks interesting sections to keep.
4. Local corrections can trigger local reruns. A strategy failure returns the video to Part 2 with a revised plan while retaining existing results.
5. Export selected clips, the complete processed video, or both. Preserve the project for later edits.

The system may flag a changed scene and propose a plan revision during production. It must not silently substitute a materially different plan for the approved one. Conservative fallbacks already contained in the approved plan can run automatically.

## 4. Planning responsibilities and evidence

| Participant | Responsibility |
|---|---|
| User | Intent, target identity, references, visual preferences, trial approval, final selection |
| Qwen planner | Scene interpretation, subject definition, available cues, assumptions, fallback proposal |
| Second reviewer | Independent critique, unsupported-assumption detection, explicit proposed revisions |
| Application | Schema validation, supported-operation checks, immutable versions, prompt construction, job scheduling |
| Local Qwen and tracking components | Repeated observations, identity checks, reacquisition, measurable tracking evidence |
| Geometry/rendering components | Orientation checks, trajectory calculation, crop/rotation/zoom, borders, export |

The structured plan should contain subject inclusions/exclusions, reference IDs, orientation evidence and limitations, missing-target behavior, framing preferences, sampling settings, fallbacks, and unresolved questions. Fixed application templates turn this plan into analysis prompts. A plan cannot create a detector or sensor capability that the implementation does not have.

Reference purposes:

- **Identity:** a clear view of the selected subject.
- **Appearance variation:** another angle, distance, or partial occlusion.
- **Orientation evidence:** a true horizon or other useful cue; not an assertion that the frame is already level.
- **Desired composition:** an example of framing, optionally with an edited crop.

One subject reference is sufficient to start. Additional references are optional. User references and system-selected samples remain distinguishable. Provider choice, credentials, cost limits, and permission to send selected images externally are explicit setup choices; no provider is integrated yet.

## 5. UX design

### Project library and three workspaces

The top-level navigation is **Design**, **Validate**, and **Produce**. Each video card shows a thumbnail, subject, state, plan version, latest result, and next user action. Batch buttons operate only on eligible videos.

| Workspace | Video states | Main actions |
|---|---|---|
| Design | Needs references; drafting plan; needs clarification; ready for trial | Add references; edit instruction; generate/review plan; queue trial |
| Validate | Trial queued/running; ready for review; needs revision; plan approved | Run trials; compare; revise; approve; set aside |
| Produce | Full run queued/running; ready for final review; selections saved; exported | Process approved videos; correct; mark keep ranges; export |

Paused, failed, interrupted, and canceled are explicit job states, separate from a video's workflow state. Restarting the UI must not change job truth.

### Design workspace

A large video player and timeline support subject selection. A reference tray holds timestamped cards with purpose, annotations, and selection overlays. A separate group shows automatic samples.

Display the plan as plain-language decisions with clickable supporting frames. Keep prompt text, raw model output, reviewer history, and provider settings in an expandable diagnostics area. Ask users only questions that change meaningful behavior. The primary handoff is **Queue for trial**.

### Trial-review workspace

Present a review inbox, synchronized original/processed playback, evidence overlays, and the plan version used. Expose subject size, smoothness, composition, leveling mode, border treatment, and missing-target behavior.

Label a change as requiring either **new analysis** or **new rendering**. Preserve the playhead when comparing runs. Make trial coverage and untested intervals visible. Primary decisions are **Approve plan**, **Revise and retry**, and **Set aside**.

### Production and final-review workspace

Show original and processed footage together, with a timeline containing separate tracks for subject uncertainty, orientation uncertainty, corrections, and keep selections. An issue queue explains why each interval needs attention and plays surrounding context.

Correct directly on the image: redraw the subject, mark absence, draw a genuine horizon, adjust orientation, or change framing. Show the affected interval before rerunning. Support undo and comparison with the prior result.

Allow marking keep/skip ranges without first repairing uninteresting footage. Export selected clips or the full result. Selections remain attached to stable source timestamps across compatible rerenders.

### Shared interaction rules

- Autosave instructions, references, plans, corrections, and selections.
- Preserve immutable versions of plans and results; do not overwrite comparisons.
- Bind approval to the tested plan and material processing settings. Changes make the new version unapproved; the old approved version remains identifiable.
- Show processing stages, progress, last checkpoint, and recoverable errors. Avoid an empty screen during frame preparation.
- Support pause/resume and restart recovery; estimate time only when supported by observed progress.
- Distinguish measured, interpolated, model-reported, and manually corrected values.
- Separate identity/tracking confidence from orientation confidence. Use labels/icons in addition to color.
- “No issue detected” does not mean “verified correct.” Model agreement does not replace visual validation.
- Advanced diagnostics expose boxes, masks when available, roll, zoom, evidence, model notes, provenance, and saved JSON.

## 6. Generalization and engineering direction

| Footage | Potential orientation evidence | Failure to avoid |
|---|---|---|
| Open ocean | Sea–sky horizon; usable orientation metadata | Confusing waves, clouds, or spray with the horizon |
| Coastal sailing | Horizon, metadata, background geometry | Forcing a perspective shoreline horizontal |
| Skiing | Usable metadata, multiple background cues, temporal camera motion | Flattening terrain or removing skier lean |
| No reliable absolute cue | Recent reliable orientation and relative motion, with growing uncertainty | Inventing a confident absolute angle |

Separate subject tracking, camera orientation, and artistic framing. Evaluate a general video tracker/segmenter alongside Qwen identity supervision; the existing sail-color specialization is not a general solution. Validate rotation against independent evidence after rendering.

The initial development host had two RTX 5090 GPUs; this is an example deployment, not a runtime requirement. The vision endpoint may run on another host. Schedule model memory explicitly; do not assume the VL model, another tracker, and long contexts fit concurrently. Prioritize correctness, resumable jobs, sequential decoding, bounded memory, and cache reuse before chasing throughput.

Preserve source timestamps and validate audio sync, variable-frame-rate footage, slow motion, lens distortion, and color handling before claiming broad format support. Current preview output does not provide HDR mastering or recover content outside the source frame.

## 7. Implementation boundary

Already present in the prototype:

- Dedicated `.venv`, local Qwen integration, rectangle selection, and target description.
- Sampled analysis, temporal context, backward recovery, per-frame geometry/refinement, smooth reframing, and blurred feathered borders.
- Configurable analysis FPS, cached observations, run metadata, basic progress records, and separate output directories.
- Synchronized comparison, frame diagnostics, uncertainty flags, and basic corrections.
- Optional Action 6 fused-attitude extraction, independent Qwen visual leveling, gyro-final rendering, and separate divergence indicators. This adapter has a provisional image-axis mapping; it is not general calibrated IMU support.

Still proposed:

- Purpose-tagged multiple references and automatic planning evidence selection.
- Qwen-generated plans, second-model review, immutable approval records, and a three-workspace batch UI.
- Durable batch orchestration, full restart recovery, representative trial scheduling, and selective reruns.
- General orientation/tracking validation, final keep-range editing, and clip export workflow.

The earlier 2 FPS example completed with backward recovery. The 10 FPS experiment is not a completed quality benchmark in this document; consult its live artifacts for status. The existing leveling error near 55.02 seconds is a regression case, not a solved problem. Automated software checks do not establish visual quality.
