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
   labeled crops and no saved text, Qwen prepopulates a draft using up to five
   ground-truth crops; without crops the editor starts empty. Saved text is
   preserved, and a regenerate control can draft again from the crops. Edit the
   text and save a draft or explicitly approve it; drafting never approves it.
3. **Approve and mark ready.** Approval records the description and current
   configuration/label/source revision. Changing these inputs makes readiness
   stale. Unapproved projects cannot be queued. The approved description is used
   directly by crop-text verification; its candidate crop description remains
   blind to the target. Legacy projects without an approved description retain
   their previous reference-description behavior.
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
