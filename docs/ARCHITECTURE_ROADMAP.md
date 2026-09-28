# Architecture and next steps

Agreed architecture: **four core components → video-level scheduling → folder-level
workflow**. Refinements stay within those responsibilities; they do not introduce
new top-level tracking components. This document sets the next development order.
The broader [project plan](PROJECT_PLAN.md) retains long-term product acceptance
checks; its earlier planner-first ordering is not a prerequisite for this roadmap.
See [current approach](CURRENT_APPROACH.md) for implemented behavior and limits.

## Responsibilities

| Owner | Responsibility | Refinements within this owner |
|---|---|---|
| C1 — Human labeling UX | Supply authoritative subject selections, absence labels, references and identity descriptions; review and correct results | Draft descriptions from selected crops for human editing/approval; preserve reference images and approval versions; efficient annotation |
| C2 — Verification | Inspect a code-generated crop and compare its description against human-approved target descriptions | Separate identity match, completeness and localization quality; expose ambiguity and contradictory evidence |
| C3 — Independent detection with verification | Find or reacquire the target without requiring a prior location; supply sampled coverage of the video | Raw/leveled detection paths, proposal retries, local search or full-frame search, all evaluated through C2 |
| C4 — Motion tracking with verification | Propagate target location through adjacent frames and report uncertainty; validate through C2 | Separate motion-update frequency from verification frequency; improve optical flow or introduce another tracker |
| V — Video-level scheduler | Decide which frame, direction and operation to process next | Expand from confident anchors toward uncertain regions in either direction; schedule discovery, verification, recovery and bounded retries |
| F — Folder-level workflow | Prepare and assign videos, collect ground truth, run batches and review results | Batch description approval, readiness checks, overnight scheduling, resume/retry and exception review |

C4 exposes motion quality and requests for verification/localization. V chooses
when to invoke C2 or C3 using that evidence and the configured policy. F controls
which video jobs run and their resource allocation, rather than choosing individual
tracking frames. Human authority belongs to C1; neither model agreement nor a
motion score can override an explicit human label.

Leveling, smooth camera-path generation, rendering and segment export remain
supporting processing/output capabilities. They consume tracking results and are
not a fifth core tracking component. A successful tracker alone does not prove
that the rendered result is level or comfortably framed.

## Feature building versus optimization

**Feature building** adds a missing usable capability or correctness contract:
for example, approving a target description, propagating a new label into a live
job, or resuming a folder batch. It is complete only when its user-visible result
and acceptance checks work end to end.

**Optimization** improves an existing capability's accuracy, stability, runtime,
GPU use or human effort. It needs a fixed baseline and measured comparison; a new
prompt, faster request or higher model score alone does not establish improvement.
Algorithm quality optimization is as important as speed optimization.

Current prototype foundations include polygon labeling and candidate approval,
blind crop-description verification, raw/leveled detection, CPU optical flow,
anchor expansion/discovery, rendering and synchronized review. This does not mean
all component contracts or the folder workflow are complete. Human approval of
descriptions, live worker label reloading and durable folder jobs remain work to
build. Existing single/dual traversal modes remain useful comparison baselines.

## Feature-building sequence

All steps below are planned work, not completion claims. Build on existing code.
Each deliverable records input revisions, observable results and limitations.

### B1 — Human-approved identity evidence (C1)

**Build:** A reference tray with frame/polygon, cropped image, drafted description,
editable text and explicit approval. Separate approved descriptions from model
notes; record revisions, target exclusions and human absence. Description approval
is an enhancement inside C1, not a separate planning subsystem.

**Verify:** Select references from two appearances of the same target. Correct an
incorrect generated description, approve it, reload the project and inspect the
saved evidence. Confirm an unapproved draft cannot silently replace approved
identity evidence. Box approval and description approval have distinct provenance.

### B2 — Shared verification result and inspection UI (C2)

**Build:** A common result carrying crop description, identity match, completeness,
localization quality where measurable, uncertainty and reasons, with exact crop
geometry and reference revision. Reuse existing blind-description comparison;
mark unavailable evidence explicitly. Route both C3 and C4 through this contract.

**Verify:** Inspect four saved examples: correct/full target, correct/clipped
target, wrong target, and loose crop containing the target. The UI must distinguish
identity evidence from box quality. A loose or clipped crop must not automatically
qualify as a precise anchor solely because identity matches.

### B3 — Independently testable detection and motion operations (C3/C4)

**Build:** Expose detection and propagation as operations with common source-space
geometry, verification evidence, provenance and failure outcomes. Keep both
raw/leveled candidates. Expose motion cadence and verification cadence separately;
record which frames were tracked, verified, independently detected or interpolated.

**Verify:** On one short labeled clip, run independent detection without a prior
box, then propagation from a human box. Inspect exact crops and coordinates for
both paths. Introduce an occlusion or tracking failure and confirm that motion
quality is not presented as identity confidence. Count Qwen calls separately from
per-frame motion updates.

### B4 — Live labels and revision-aware scheduling (C1/V)

**Build:** Consume changed labels at task boundaries and before publishing results;
insert new anchors and off-grid frames, update context revisions, retire stale
anchor descendants and enqueue bounded forward/backward recovery. Preserve
unrelated completed work. Saving labels during a job already works; this step
makes the worker consume them without a full restart.

**Verify:** Approve a box during an in-flight Qwen request and confirm the human
label wins. Add an unsampled label, then replace/remove an anchor. Inspect revised
queue/provenance and resume from a checkpoint: stale work must not restore the
old label. Report the consumed label revision in the UI. See the detailed
[live-label acceptance checks](PROJECT_PLAN.md#incremental-prototype-work--live-human-label-updates).

### B5 — Folder preparation and batch assignment (F, reusing C1)

**Build:** A video library with per-video target/instructions, references, editable
initial descriptions, assigned processing settings and explicit Ready status.
Support batch review while retaining per-video identity evidence. Make missing
or unapproved required inputs visible. A richer model-generated planner remains
optional future work, not a prerequisite for this usable batch flow.

**Verify:** Prepare at least three videos with different targets/settings. Edit
and approve descriptions in batch; leave one video incomplete. Reload the library
and confirm each assignment persists and only ready videos can be queued.

### B6 — Durable overnight processing (F)

**Build:** Persistent jobs with explicit input revisions, progress, checkpoints,
resource limits, pause/resume/retry, error isolation and output provenance. Separate
workers from the web server. Later label revisions must be recorded when B4
consumes them; a job must not claim it used only its initial inputs when it did not.
Begin with reliable serial execution before tuning multi-GPU concurrency.

**Verify:** Queue the prepared folder, restart the UI and interrupt a worker.
Confirm completed work survives, unfinished work resumes, one failed video does
not block the rest, and duplicate jobs cannot write the same outputs. Every result
must identify its settings and consumed label/description revisions.

### B7 — Batch exception review and focused reprocessing (F/V)

**Build:** A cross-video list of uncertain intervals and conflicting evidence,
linked to shared labeling/approval controls. Show which corrections were consumed
and which results require regeneration. Reprocess affected regions, then render
for final review and selection of interesting segments. Segment export remains a
separate output milestone in the broader plan.

**Verify:** Correct failures from two overnight results, enqueue repairs, and
confirm affected results change while unrelated completed work is retained. Open
synchronized comparisons at the flagged times and inspect correction provenance.

## Optimization backlog

Establish a small fixed evaluation set while building B1–B3: clear/blurred targets,
lookalikes, clipping, occlusion, reappearance, camera motion and manual corrections.
Use evaluation labels separately from the reference labels supplied to the model.
Expand to open ocean and skiing as footage becomes available. Record quality,
cost and human effort, not only the verifier's own scores.

| Owner | Optimization experiments | Evidence of improvement |
|---|---|---|
| C1 | Faster navigation, reference suggestions, batch editing, fewer annotation gestures | Time/clicks per reviewed label and correction rate, with unchanged annotation accuracy |
| C2 | Description prompts, reference wording, ambiguity handling and threshold calibration | False accepts/rejects against human judgments; completeness and box-quality errors reported separately |
| C3 | Raw versus leveled inputs, crop retries, search resolution, sampling cadence | Detection coverage, identity switches, box overlap/subject clipping and Qwen time/calls on the same clips |
| C4 | Optical-flow settings or alternative trackers; motion-aware relaxation and adaptive verification intervals | Drift, time to detect loss, verified coverage, localization error and Qwen calls per source minute |
| V | Anchor priority, direction choice, discovery density, stopping rules, cache reuse | Total verified coverage versus cost, recovery delay, stale/repeated work and human correction effort |
| F | GPU/model concurrency, request batching and overnight job order | Completed ready videos per night, peak memory, failures and resumability, without degraded quality |

Start optimizations after the owning component has an inspectable baseline. Fix
correctness defects immediately; do not postpone them as optional optimization.
Do not optimize all parameters at once: hold references, footage and unrelated
settings fixed, preserve the old results, and compare identical timestamps.

## Delivery order and completion record

Prioritize **B1 → B2 → B3 → B4 → B5 → B6 → B7**. Small experiments can accompany a
working component, but should not displace the next missing end-to-end capability.
Do not expand batch concurrency before jobs can reliably resume and isolate
failures. General scene planning/reviewer integrations can follow the usable
label-driven batch workflow without changing this architecture.

For each step or optimization, record: feature/experiment ID, commit, settings and
input revisions, demonstrated artifact, validation performed, measured limitations
and next incomplete step. Commit and push completed changes; keep private media,
runtime outputs and credentials out of the repository.


## Implementation update — folder batch foundation

B5 and the serial foundation of B6 now have a working end-to-end implementation;
see [batch workflow](BATCH_WORKFLOW.md). C1/C2 also gained editable description
approval and direct verifier consumption of that approved text. B7 has per-run
review links and copying reviewed corrections into a new source revision.

This does not complete B1–B7: a multi-reference tray, unified quality contracts,
live-label scheduling, selective repair, richer resource scheduling, mid-video
controls and a cross-video interval-review UI remain outstanding. Queue pause is
after the current video; retry resumes saved inputs using existing pipeline caches.


## Performance and operating reliability

The [performance, reliability and operations plan](PERFORMANCE_RELIABILITY_OPERATIONS.md)
tracks GPU rendering, measurement, process supervision, recovery, observability and
queue resource scheduling within the existing components. It separates implemented
behavior from proposed work and gives acceptance checks for each delivery step.
