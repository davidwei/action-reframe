# Folder-level batch workflow

Open **`/library`** on the review server. The workspace is the folder supplied via
`--workspace` (or the documented default). No video/model/machine path is fixed in
the implementation. The library discovers videos and project configs directly in
that folder; recursive subfolder import is not yet implemented.

## Prepare, queue, process, review

1. **Add a video project.** Select a video for a quick preview, then Add project.
   Previews use cached H.264/AAC clips, avoiding browser HEVC/MOV decoding failures
   that can play sound with a frozen picture. Twenty-second clips are generated
   on demand at up to 640×360 and 15 FPS; the source-position slider seeks across
   the entire video. Frame previews remain available during conversion. Original
   videos and analysis/output FPS are unchanged. The project starts
   New with no assumed subject. Open the focus editor to draw its first box, or
   use Review descriptions to jump to the description section of Video focus. New projects default
   to anchor tracking. You can save additional polygon labels before analysis.
   Existing projects are listed separately, including multiple targets per video.
2. **Prepare inputs.** Open labels/settings to set analysis FPS, tracking mode and
   confidence thresholds. Use Review descriptions to open the description editor in Video focus. With
   labeled crops and no saved text, Qwen prepopulates a draft using all
   ground-truth crops; without crops the editor starts empty. Saved text is
   preserved, and a regenerate control can draft again from the crops. Edit the
   text and save a draft or explicitly approve it; drafting never approves it.
3. **Approve and mark ready.** Approval records the description and current
   configuration/label/source revision. Changing these inputs makes readiness
   stale. Unapproved projects cannot be queued. The approved description is used
   directly by crop-text verification; its candidate crop description remains
   blind to the target. Legacy projects without an approved description use the same blind crop
   descriptor on their initial reference crop.
4. **Queue selected projects.** Select ready projects individually or select all
   ready. Each run receives a saved input snapshot and an isolated output folder.
   Queueing is separate from starting. Duplicate pending jobs for the same
   revision are deduplicated. New completed-run requests get separate outputs.
5. **Start/resume queue.** One video runs at a time through analysis, rendering and
   comparison. Closing/restarting the web UI does not stop the separate worker.
   Failures are recorded and later jobs continue. An existing single-video job
   must finish before starting the batch; preparation and queueing remain usable.
6. **Review results.** Open a saved run's focus view or synchronized comparison.
   Inspect flags, add labels or approve estimates. Batch-run review edits are
   stored separately from frozen processing labels, so they cannot silently
   change a queued/running job. Use **Copy corrections to source**, review and
   approve the project again, then queue a new revision. This action refuses to
   overwrite a source project that changed since the run was prepared.

Settings and direct analysis commands on saved batch-run configs are blocked:
use their source project for a new run. This keeps old run settings reviewable.
Corrected jobs currently run a new isolated analysis; selective reprocessing of
only affected regions and live worker label updates are not yet implemented.

## Queue lifecycle and restart behavior

Jobs move through `queued → starting → running → succeeded / failed`. Unexpected
runner loss becomes `interrupted` when Start/resume starts a worker and checks
process locks. **Retry saved inputs** requeues failed/interrupted runs in their
original output folder, reusing pipeline caches where supported. It does not
change the input snapshot or guarantee that every processing stage is skipped.

**Pause after current video** stops dispatching subsequent jobs; it does not
interrupt an active video. Cancel applies only to queued jobs. After a machine
restart, open the library, Start/resume to reconcile interrupted work, retry the
interrupted job if desired, then Start/resume again if the queue is idle. There
is no auto-start system service or clock-based overnight scheduling yet; start
the queue when ready to leave it unattended.

A workspace worker lock prevents duplicate schedulers. A separate per-run lock
protects each active runner and survives a scheduler/UI restart because the
runner is an independent process. SQLite transactions protect queue transitions.
A source file whose size or modification time changed after queueing is rejected
at execution. Source videos are not copied or fully content-hashed.

## Stored data

- `.batch/queue.sqlite3`: preparation approvals, persistent jobs and pause state.
- `.batch/runs/<id>/project.json`: processing configuration snapshot.
- `.batch/runs/<id>/inputs.json`: source project, input revision, source file
  identity, approved description and human labels.
- `.batch/worker.log`: scheduler log.
- `outputs/batch/<id>/`: existing pipeline artifacts, frozen `corrections.json`,
  processing `job.log`, and optional `review_corrections.json` for subsequent edits.

These are local runtime data excluded from Git. Runtime snapshots may use resolved
paths; moving the workspace requires re-preparation rather than assuming saved
jobs are relocatable. Original project configs and videos are not overwritten by
batch processing. Batch preparation approvals are explicit user actions, not model
self-approval.

## Verification and limits

Automated checks cover stale readiness, snapshots, duplicate requests, failure
isolation, retry, locks, interrupted-state recovery, source-correction conflicts,
and direct use of approved descriptions. A real subprocess worker test renders a
fully human-labeled synthetic video through the existing pipeline without Qwen,
after a deliberately failing job. Browser checks cover approval/queue/start,
reference crops, creation in a nonempty workspace and pre-analysis labeling.
These validate workflow correctness, not model tracking quality on real footage.

The first implementation intentionally uses serial processing. Multi-GPU dispatch,
per-job resource limits, mid-video pause/cancel, automatic checkpoint migration,
per-reference description approvals, batch export/trim controls, and a combined
cross-video interval-review timeline remain future work. The current job table
links to each video's existing flags and comparison view.


## Project states and actions

| State | Meaning | Actions |
|---|---|---|
| New | Video added; no user labels or text yet | Label subject; Review descriptions; Discard project |
| Draft | Some user input exists; readiness requirements are incomplete | Label subject; Review descriptions; Discard project |
| Ready | At least one cropped box and an approved description for current inputs | Label subject; Review descriptions; Queue processing; Discard project |
| Processing | Queued, starting or running | Label subject; Review descriptions; Open video focus; Discard project |
| Done | Successful processing for current inputs (including unchanged legacy output) | Label subject; Review descriptions; Open video focus; Watch side by side; Discard project |

These names are canonical across states. **Label subject** opens Video focus at
`#subject-labels`; **Review descriptions** opens that same workspace at
`#identity-description`. **Open video focus** opens the current run, showing
progress during processing and results afterward. There is no separate generic
“edit inputs,” “view progress” or “review result” project action. Queue-specific
pause, cancel and retry controls remain in the queue; download/comparison controls
remain in Video focus.

Queued/Running remain job substatuses. Failed or interrupted runs do not count as
Done: their project remains Ready if inputs are still approved, with error/retry
controls in the queue. Previous successful runs remain accessible. Editing inputs
returns to Draft unless an older immutable run is still Processing; its snapshot
continues unchanged.

Discard is reversible archival, not file deletion. Queued jobs are cancelled;
running jobs finish before the project disappears from Existing projects. Source
videos, labels, descriptions and outputs are retained. Discarded projects can be
restored in the library. Restoring does not restart cancelled jobs automatically.

Each project (including discarded projects) shows **Last updated** in the browser's
local time zone, with an exact UTC timestamp on hover. It reflects the latest
saved configuration, labels, description/approval, discard/restore, job status or
processing output update. Merely refreshing the library does not change it.

### Description review and consistency checks

Video focus → Review descriptions displays every positive human selection (including
its initial reference, overridden by any correction at that frame). Polygon labels
use the same masked source-space crops as tracking. Each card shows its frame/time,
crop image, independent crop description, identity confidence, discrepancies,
reason, and completeness assessment. These text-consistency scores do not reduce
human labels’ authoritative 100% tracking confidence.

1. `crop_description.describe_crop` describes each image with one identical blind
   prompt, whether it is a human selection or a detected box. It receives no target
   instruction, role hint, earlier description, or detector claim.
2. Qwen summarizes only those independent descriptions into an editable identity
   description, preserving uncertainty, contradictions and appearance variations.
3. `description_comparison.compare_descriptions` compares the summary against each
   crop description. Tracking verification calls this exact same function/prompt.
   Confidence is its match score when target presence is supported, otherwise zero.
   Completeness is separate. Scores are model judgments, not calibrated probabilities.
4. Each score must reach 80% to pass this consistency check. Below-threshold cards
   show feedback. **Revise using feedback** retries step 2 once per click and then
   rechecks every crop; cached image descriptions remain unchanged. There is no
   unbounded automatic retry loop or automatic approval. Conflicting labels may
   require human correction rather than a more generic summary.
5. **Check against crops** checks manually edited text without rewriting it.
   Text edits hide old scores; label/source changes invalidate cached evidence.
   Saving/approving remains explicit and may retain unresolved warnings: consistency
   is review feedback, not a replacement for human authority or a new Ready gate.

Observations, summary requests, comparison responses and each completed attempt are
stored under the workspace `.batch/description_drafts/`, keyed by source/labels and
prompt version; observation caches additionally separate models. Existing tracking
results are not rewritten. New tracking calls use the updated verifier version.

### Priority rerender jobs

Projects with saved analysis offer **Queue Rerendering (no re-analysis)** in the
folder view. This is available without approving a new analysis plan. It is hidden
while that project already has queued/running work or is being discarded.

Rerenders share the persistent queue with analysis jobs, but run first among waiting
jobs. Each group uses FIFO order. A running job is never interrupted. The queue
shows the same priority ordering and labels jobs **Rerender only · priority** or
**Analyze + render**. Start/resume, pause, cancel and retry work for both types.

A rerender copies the latest successful run's saved observations, leveling
observations and reference crop into a new output folder; legacy project analysis
is the fallback. Review corrections on that run are included. Source-project label
changes since the run was queued override corresponding saved labels. Current
render settings (dimensions, framing margins, confidence threshold, leveling and
border settings) apply, but tracking/target analysis is reused. Changing the target
or wanting new detections still requires an analysis job.

The worker runs `--stage render`, producing both focused and side-by-side videos,
new metadata sidecars and frame transforms. No model requests or tracking passes
are performed. Prior video results and analysis files remain intact. Source changes
since a batch analysis snapshot are rejected; unavailable analysis is reported
before a job is queued. Rendering remains CPU/encoding work and runs serially with
analysis to avoid resource contention. Repeated rerender submissions can delay
waiting analysis jobs; they do not preempt active work.

### Absent-frame checks

Description review also includes each explicitly **Mark target absent** frame as a
negative example. With no selected box, its image is the full source frame (the
shared descriptor still applies its normal image-size limit). Level-only edits and
an unset initial reference are not treated as absence labels.

Present crops must score at least 80%; absent frames should score at most 20%.
Intermediate or high absent-frame scores are flagged for review. This is a diagnostic
expectation, not a change to the tracking acceptance threshold. The actual computed
score remains visible: the human absence label never forces the model result to zero.
Both kinds of examples call the identical blind image descriptor and text comparator;
neither model call receives the expected label. A full-frame negative is not the same
visual test as every possible cropped region within that frame.

Absent observations are supplied separately as contrast evidence in both initial
drafting and feedback retries. Their shared scene features must not be mistaken
for distinguishing identity features. The resulting paragraph describes the common
subject as it appears in one photograph, without discussing a set of images or
background scenery. Subject features must remain supported by the positive
descriptions; negative scenes cannot introduce invented or opposite features. Original image descriptions are reused during rechecks/retries.

### Model failures during description review

Description review distinguishes HTTP/server errors, connection failures, timeouts,
empty answers, truncated output, and invalid JSON/schema. The main message includes
the affected stage and frame where applicable; **Model error details** exposes HTTP
status or finish reason, token usage, elapsed time, request ID, response excerpt and
audit-file locations. A successful HTTP response can still contain invalid model
output; it is not shown as a successful description or replaced with a fabricated score.

The shared crop-description and text-comparison calls request JSON-object output and
allow 1,000 output tokens. A confirmed `finish_reason=length` triggers one retry with
double the budget, capped at 4,096; another truncation is an explicit error. Summary
calls use their own initial budget and the same bounded truncation retry. Transport
and server errors are not automatically retried in this path, avoiding retry storms
when the model server is busy. Previously completed crop observations remain reusable.

Raw response envelopes are saved before parsing, including unsuccessful format
responses. Request audits omit inline image bytes; source crop images are retained
separately. Error audits and raw responses live beside the description-review attempt
or tracking verifier artifacts. These runtime records may contain private descriptions
and are not checked into Git. Historical parser failures from before this logging
change cannot be conclusively diagnosed if their original raw response was discarded.


### Object-focused descriptions

The shared blind crop prompt emphasizes the visible foreground object's type,
shape, colors, markings and parts. It omits surrounding scenery and separates the
features of multiple visible objects. Background-only images must still explicitly
report that no distinct object is visible. This prompt is identical for human crops,
detected crops and full-frame absent examples, without target identity hints.

Drafting and feedback revision describe the common subject as one short caption of
one photograph, rather than an account of multiple source images. Absent examples
are separate contrast evidence: attributes shared with those scenes are weak
identifiers, so the draft should favor supported distinctive object features. It
must not enumerate the negative scenes, invent differences or drop the basic object
category merely because a different object shares it. Crop prompt version 2
invalidates prior crop-observation/verification caches when new work is requested;
it does not rewrite saved human-approved text or completed video analysis.

### Reading anchor progress

Older logs use `N/T examined; A anchors; Q queued` to describe the scheduler inside one video:
`N` counts distinct covered sample positions (including human labels and failed
attempts); `T` counts the union of analysis samples, discovery samples and manual
frames. `A` counts reliable propagation seeds. `Q` counts pending forward/backward
propagation tasks, not folder jobs or remaining discovery work. Zero propagation
tasks switches the scheduler to discovery of unresolved eligible samples. A newly
qualified anchor can start more propagation. Progress is published before and after
operations, so repeated counters do not necessarily indicate duplicate inference.
The examined ratio is not a wall-time completion percentage; the scheduler can finish
without examining every position on the finer analysis grid.

### Three-timescale coverage reporting

Folder job rows and Video focus now share three coverage cards:

| Counter | Denominator | Unique position count |
| --- | --- | --- |
| Discovery | Actual 2 FPS discovery grid within the selected interval, including its endpoint | Positions where independent discovery was attempted |
| Crop verification | Actual propagation checkpoints: analysis grid plus discovery/manual additions | Positions with at least one crop-verification result or error, across either path |
| Optical tracking | Source frames in the selected interval, inclusive | Frames on which the optical tracker actually ran an update |

Rates are taken from the run settings, not hardcoded to 2/10/30 FPS. No counter
claims to predict elapsed-time completion. Discovery may resolve positions through
reliable tracking or explicit human labels without scanning them; this appears as
**resolved without scanning**, separate from scans and remaining discovery positions.
Conflict-driven off-grid discovery is reported separately from the regular grid.

Each card separates unique positions from total attempts and cached-result reuses.
An attempt is one discovery operation, one path's crop verification, or one optical
frame update—not one HTTP/model request. Both paths, detection retries and backward
visits can increase attempts without increasing unique coverage. Cached results
establish coverage but count as reuses rather than fresh attempts.

Verification position outcomes use the latest result for each path: accepted if
any path meets the confidence threshold and completeness check, otherwise rejected
if a completed rejection exists, otherwise errored. These are crop-verification
outcomes, not a guarantee the final path selector accepted that frame. Optical
positions are usable if any recorded update produced a usable prediction; failed
repeat visits still appear in attempt counts. Per-attempt errors remain visible
even if a later retry succeeds.

`tracking_work.jsonl` records completed work events under an analysis fingerprint;
`coverage_progress.json` provides lightweight UI updates. Events are replayed on
resume without recounting already-recorded work. The normal anchor checkpoint
continues to own scheduling decisions. A partial/truncated event log is flagged as
incomplete rather than silently claiming exact historical counts.

Older active runs expose discovery coverage from existing scheduler state. Their
unrecorded verification and optical history is shown as **Not recorded**, not zero.
New or instrumented resumed runs record all three counters; a resume lacking the
historical event log labels its counts partial. Deployment does not interrupt an
active old runner to obtain counters. Old logs retain their original wording;
new-run logs report the three coverage totals, anchors and propagation tasks.

Progress cards also show unique frames with **medium or higher** object confidence
(at least the configured acceptance threshold), and the **high / anchor-eligible**
subset (at least the configured anchor threshold, independently localized,
complete, and without a conflict). High counts are included in medium-or-higher
counts; they are eligible results, not the number of anchors actually scheduled.
For discovery these describe the selected detection. Crop verification counts
use the latest result per path, counting a frame once if either path qualifies.
These statistics describe each action's evidence, not final cross-branch decisions.
Optical motion quality is not identity confidence: only motion checkpoints with
crop verification receive object-confidence counts. Intermediate optical-only
frames remain unverified, and propagated boxes cannot become anchors without
independent localization. The number of positions with recorded confidence is
shown separately. Older runs show unavailable confidence counts; active workers
must finish before new jobs collect these additional statistics.

Video focus settings lock only while that specific project's job is starting or
running. Other source projects (including queued projects) remain editable;
already queued jobs retain their saved input snapshots. Saved batch-run snapshots
remain read-only. Direct analysis/render launches still respect the shared queue's
execution lock; editing an idle project's settings does not start another job.

Frame-local model-output failures (truncated, malformed, or empty answers) are
recorded in `analysis_failures.json` and the scheduler checkpoint. The Video focus
Review queue lists their exact frame, path, and error even before rendering;
clicking an entry opens that frame. Frame Analysis also displays the error.
A successful alternate path remains usable. Failed outputs never count as absence
or identity confidence and are excluded from subsequent forward/backward context.
A failed propagation checkpoint ends that branch; discovery continues elsewhere.
Failed discovery positions count as examined, so resume does not loop indefinitely
on them. Review entries retain failure history even if another attempt recovers the
frame; human corrections remain authoritative. Transport and unexpected system
errors still stop the job. Already-running workers need a new runner to load this
behavior; their failures are not silently reclassified in memory.

### Stop active processing

Running and starting batch jobs expose **Stop processing** in the Folder job
list. The Linux server identifies the exact runner by workspace and job ID,
uses pidfds to avoid recycled-PID mistakes, and terminates its child processes
without signaling the queue worker or unrelated jobs. It verifies release of
the job lock before marking the job **Interrupted**. Cached frames, input
snapshots, and checkpoints remain available to **Retry saved inputs**. The queue
may proceed to its next job; use Pause queue as well to prevent that. A stopped
job does not restart automatically. Queued jobs still use Cancel. This stop
implementation requires Linux `/proc` and pidfd support.

Folder project and job rows show code identity at processing start. Analysis and
render versions are separate: a rerender records its new renderer and preserves
the source analysis version. Executable-source fingerprints include uncommitted
changes; documentation-only commits do not falsely invalidate them. Older runs
without provenance say **Version not recorded**. Compatible cached results can
originate from earlier code, so a current runner does not imply every observation
was recomputed. For outdated or unknown work, **Re-run analysis** queues approved
inputs in a new run and **Re-render (no re-analysis)** uses the priority render
queue. Active jobs remain protected, and unapproved projects link to input review.

Video focus navigation is ordered: Previous reviewed, Previous tracked, Previous
sampled, Previous frame, Next frame, Next sampled, Next tracked, Next reviewed.
Tracked navigation requires an accepted box at that exact observation (or a human
label), not interpolated rendering coordinates; absence labels override estimates.

Navigation uses Previous and Next fieldsets with short button labels; accessible
labels retain the full direction and frame type.
