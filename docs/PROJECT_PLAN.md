# Action video reframing: implementation plan

See [current approach](CURRENT_APPROACH.md) for the implemented tracking/review behavior, agreed tradeoffs, and the boundary between current functionality and planned work.

This plan implements [PROJECT_DESIGN.md](PROJECT_DESIGN.md). Each step ends with a result the user can inspect. These are planned milestones, not claims of completed functionality. Reuse existing prototype components where they satisfy the acceptance checks.

Work in order unless a dependency explicitly permits otherwise. Finish a narrow end-to-end workflow before broad performance tuning. Keep the existing comparison and source videos intact. Use the dedicated project environment.

## Step 1 — Establish a reproducible baseline

**Build:** Inventory existing commands, configs, outputs, and known defects. Record baseline settings and source timestamps. Create a small regression manifest covering clear identity, absence, recovery, and the leveling failure near 55.02 seconds. Preserve the 2 FPS result and distinguish any incomplete 10 FPS run.

**Result:** A baseline report with links to playable clips, matching frame diagnostics, and exact settings.

**User verification:** Open the baseline comparison, seek to each manifest timestamp, and confirm the report matches the footage. Confirm the original video and prior output still exist.

**Pass when:** Another run can be compared at the same source timestamps, and known failures are documented without being labeled fixed.

## Step 2 — Add project records, immutable versions, and the library

**Depends on:** Step 1.

**Build:** Persist videos, instructions, preferences, references, plan versions, trial/full runs, approval records, corrections, and selections. Give records stable IDs. Add the Design / Validate / Produce library with per-video state and next action. Import legacy example configs without overwriting them.

**Result:** A library containing multiple videos with independent saved state.

**User verification:** Import two videos, give them different instructions, reload the browser and restart the server. Confirm both retain their state and link to the correct source. Create a new draft version and reopen the old version.

**Pass when:** State survives restart, versions are distinguishable, and one video's edits cannot alter another video.

## Step 3 — Implement subject and reference collection

**Depends on:** Step 2.

**Build:** Add the reference tray with frame timestamp, purpose, note, subject box/selection, and optional desired crop. Require one identity reference; permit appearance, orientation, and composition references. Generate separately labeled automatic samples and short neighboring sequences.

**Result:** A saved evidence bundle viewable as reference cards and playable sequences.

**User verification:** Select the other dinghy, add a second appearance and an orientation reference, then reload. Open each card and confirm exact source position and overlays. Start another draft with only one identity reference.

**Pass when:** References retain their purposes and annotations; system samples do not overwrite user choices; one reference is enough to continue.

## Step 4 — Generate a structured Qwen plan

**Depends on:** Step 3.

**Build:** Define the plan schema and prompt template. Include subject components/exclusions, evidence IDs, orientation cues and limitations, framing choices, sampling rate, missing-target handling, and fallbacks. Validate types, references, supported capabilities, and finite parameter ranges. Show a plain-language summary linked to evidence.

**Result:** A versioned Qwen draft plan with its inputs and validation report.

**User verification:** Request “follow this boat smoothly and keep the camera level.” Confirm the plan identifies the other boat and explains its orientation evidence. Supply a slope/shoreline example and verify that the plan does not assume the boundary is horizontal. Enter “include the full sail” and inspect the new version.

**Pass when:** Plans are traceable to actual references, invalid/unsupported plans cannot be queued, and iteration preserves earlier drafts. No full-video analysis is needed for this step.

## Step 5 — Add independent plan review

**Depends on:** Step 4.

**Build:** Add a configurable reviewer interface and one working provider integration. Provider/account choice remains a setup decision. Send selected evidence and intent for an independent assessment, then the draft for critique. Store critiques, proposed changes, and a validated final revision. Disclose which selected images go to an external provider; never silently switch providers on failure.

**Result:** A review view showing draft, critique, revised plan, and unresolved issues.

**User verification:** Use a deliberately flawed draft that forces a shoreline horizontal. Confirm the review workflow surfaces the assumption and records the correction. With the reviewer unavailable, confirm an explicit error/retry state rather than a fabricated successful review.

**Pass when:** A real reviewed example is inspectable, model disagreement is preserved, and the application rejects unsupported revisions. Use deterministic fixtures for workflow failure tests; do not treat one model answer as a quality guarantee.

## Step 6 — Build the durable offline job queue

**Depends on:** Step 2; connect reviewed plans from Step 5 before trial execution.

**Build:** Separate workers from the web server. Persist queue entries, immutable input versions, stage progress, checkpoints, errors, and output locations. Add pause/resume/cancel/retry semantics, worker heartbeat, interrupted-job detection, and resource-aware scheduling. Prevent duplicate workers from committing the same job. Keep partial outputs separate from completed artifacts.

**Result:** A batch dashboard that remains accurate across UI and worker restarts.

**User verification:** Queue two small jobs. Close/reopen the browser, restart the web server, then interrupt and restart a worker. Confirm completed observations are reused, interrupted work is visible, and no job is falsely marked complete. Retry a simulated model timeout.

**Pass when:** Jobs resume safely, failure of one video does not erase or block unrelated results, and completed output appears only after validation. A restarted UI can identify jobs launched before it restarted.

## Step 7 — Connect plans to scene-aware analysis

**Depends on:** Steps 4–6.

**Build:** Compile the validated plan into bounded analysis prompts and actual processing settings. Remove mandatory shoreline assumptions. Store orientation evidence type and uncertainty separately from tracking confidence. Retain directional history and backward recovery. Include video identity, plan/settings, model/template versions, and dependencies in cache validity. Reset context at scene boundaries where appropriate.

**Result:** A short processed interval whose diagnostics identify the governing plan and evidence.

**User verification:** Process the same interval with two materially different subject or leveling plans. Confirm the appropriate observations are regenerated. Change only border appearance and confirm compatible observations can be reused. Inspect forward/backward context provenance and an ambiguous-orientation fallback.

**Pass when:** The plan actually controls behavior, unsupported capabilities are not claimed, and cached results cannot silently cross incompatible runs.

## Step 8 — Run representative trial batches

**Depends on:** Steps 5–7.

**Build:** Select user-reference intervals, distributed samples, and likely difficult intervals with configurable duration/budget. Show tested coverage before queuing. Include temporal padding for tracking/smoothing, and identify the displayed evaluation region. Reuse analysis only when its context and dependencies match; do not blindly splice trial observations into full runs.

**Result:** Trial comparison videos, diagnostics, coverage maps, and settings for every queued video.

**User verification:** Queue trials for two videos and leave the UI. Return to two playable results. Confirm each includes user references and distributed coverage, shares original/processed timestamps, and is labeled with the correct plan version.

**Pass when:** Trials complete independently through the queue, partial failures are recoverable, and users can see untested portions of each source.

## Step 9 — Implement trial review and approval

**Depends on:** Step 8.

**Build:** Add the Validate inbox, synchronized playback, evidence-linked issues, run comparison, and Approve / Revise and retry / Set aside actions. Bind approval to the plan, relevant references, material settings, and trial evidence. Clearly distinguish “ready for trial” from “approved for full processing.”

**Result:** User-approved versions eligible for production, with a recorded approval history.

**User verification:** Approve one video and revise another. Confirm only the approved version is eligible for full processing. Change its subject, orientation strategy, or analysis FPS; confirm the new version requires validation while the earlier approved result remains accessible. Switch trial runs at the same playhead position.

**Pass when:** No stale approval can authorize changed analysis, and users can explain exactly what they approved and what coverage was tested.

## Step 10 — Process approved videos in full batches

**Depends on:** Step 9.

**Build:** Add Process approved videos. Execute full forward analysis, backward recovery, camera-path generation, rendering, comparison, and artifact checks with the approved immutable inputs. Report stages and checkpoint progress. Flag strategy failures without silently replacing the approved plan.

**Result:** Complete processed videos and review records linked to approved versions.

**User verification:** Submit one approved and one unapproved video. Confirm only the approved video starts. Check start/end duration, source/output alignment, audio sync, actual analysis cadence, backward report, and completed-artifact status. Interrupt a full run and confirm it resumes.

**Pass when:** The full path is approval-gated, reproducible, resumable, and produces a playable result. Configuring 10 FPS must not change playback speed.

## Step 11 — Add orientation validation and general tracking

**Depends on:** Step 10 for the complete workflow; small regression experiments may begin earlier.

**Build:** Separate identity/tracking, orientation, and framing modules. Evaluate a general tracker/segmenter with Qwen identity supervision. Add measured horizon/background evidence and relative camera motion; integrate motion metadata only after availability, synchronization, and calibration are verified. Check residual tilt against independent evidence. Include equipment in subject bounds, support conservative ambiguous-orientation behavior, and flag forward/backward disagreement.

**Result:** A visual regression report for coastal sailing, open ocean, skiing, occlusion, and camera motion. Candidate implementations are compared with the existing baseline.

**User verification:** Inspect the known 55.02-second failure and independently annotated horizon examples. Confirm ski slopes and natural subject lean are preserved. Confirm the tracker follows the selected subject rather than whichever object matches a color. Inspect behavior when no absolute orientation is observable.

**Pass when:** Measured comparisons show supported corrections on the regression set, subject coverage is retained, and ambiguous cases are flagged. Define acceptable roll error, clipping, identity errors, and jitter before evaluating candidates. If ocean/ski samples are unavailable, mark those checks pending rather than claim general support.

## Step 12 — Add final issue review and selective correction

**Depends on:** Steps 10–11.

**Build:** Add separate tracking/orientation timeline lanes, an explanatory issue queue, direct image corrections, editable correction scope, undo, and rerun previews. Calculate dependency-aware invalidation: a correction may affect later temporal context, backward recovery, or smoothing beyond the selected interval. Present the actual rerun scope and keep old results available.

**Result:** Corrected output versions with a visible provenance trail.

**User verification:** Fix a wrong box and a wrong angle, inspect affected intervals, and compare before/after. Confirm unrelated valid results remain usable. Send a systemic failure back to plan revision and verify the approval rules still apply.

**Pass when:** Corrections demonstrably improve the chosen interval, propagation is not hidden, and undo restores the previous result.

## Step 13 — Select interesting segments and export

**Depends on:** Step 12.

**Build:** Add keep/skip ranges, labels, range editing, and exports for selected clips and complete videos. Attach selections to source timestamps, retain them across compatible rerenders, and provide an export manifest with source ranges and plan/run versions. Keep the full processed timeline available.

**Result:** Playable selected clips, a full-video export option, and saved selection metadata.

**User verification:** Mark three sections, reload, adjust one boundary, and export. Check each start/end, audio sync, expected ordering, and correspondence with saved selections. Skip an uninteresting flagged segment without having to correct it.

**Pass when:** Exports match the visible selections, preserve the original, and can be reproduced from the saved project.

## Step 14 — Validate long videos, formats, and FPS experiments

**Depends on:** Steps 10–13.

**Build:** Profile long runs, use sequential decoding and bounded working sets, schedule GPU memory explicitly, and evaluate hardware decode/encode where beneficial. Validate variable-frame-rate timing, slow motion, lens handling, and SDR/HDR behavior; unsupported cases must be clearly identified. Add fair 2/5/10 FPS comparisons with other settings and evaluation intervals fixed.

**Result:** A compatibility and performance report, saved experiment runs, and documented practical limits.

**User verification:** Run a multi-video unattended batch, including a long clip and available nonstandard timing formats. Check recovery after interruption, memory/disk use, playback timing, audio, and visible color changes. Compare 2/5/10 FPS at identical source positions and inspect runtime, identity errors, clipping, leveling, jitter, and correction effort.

**Pass when:** Supported formats pass their explicit checks, unsupported behavior is not silently mishandled, and the FPS recommendation is based on observed quality and cost. No universal quality benefit is assumed for higher FPS.

## Delivery checkpoints

| Checkpoint | Steps | User-visible outcome |
|---|---|---|
| Plan preparation | 1–5 | Select references, iterate on an evidence-linked plan, inspect second-model review |
| Offline validation | 6–9 | Queue multiple trials, return to results, revise or approve exact versions |
| Full production | 10 | Batch-process only approved videos and review complete outputs |
| General action review | 11–12 | Better scene-specific estimation and efficient, traceable corrections |
| Editing and hardening | 13–14 | Export selected moments and run validated long-video workloads |

For every checkpoint, record the demonstrated artifact, the verification performed, remaining limitations, and the next incomplete step. A working button, generated JSON, or passing unit test alone is insufficient when the acceptance check requires a visual result.


## Incremental prototype work — live human-label updates

**Status:** Proposed; saving labels during processing is implemented, automatic
reload inside an active analysis pass is not.

**Build:** Track label revisions at task boundaries and before publishing model
results. Insert new human anchors, invalidate affected context/cache dependencies,
retire descendants of replaced/removed anchors, and enqueue bounded bidirectional
recovery. Preserve unrelated completed work and checkpoint the consumed revision.
Debounce repeated edits and prevent duplicate tasks. Keep the existing UI settings
and new-job lock during active processing.

**Result:** Saving an approval while analysis is running visibly updates the
worker's active label revision and schedules relevant recovery without restarting
the entire run.

**User verification:** During a run, approve a zero-confidence box on an already
processed frame and draw another label on an unsampled frame. Confirm both become
human anchors, propagate in both directions, and survive an in-flight model result.
Replace and remove a label, then restart from a checkpoint; verify stale anchor
work cannot restore the old label. Confirm unrelated results remain unchanged.

**Pass when:** The worker reports the consumed revision, final results preserve
all current human labels, obsolete work cannot overwrite them, and the request
log shows that only affected work was repeated.
