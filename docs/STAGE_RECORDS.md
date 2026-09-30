# Stage records and efficient reruns

Implemented September 28, 2026. Evidence is stored separately from scheduler state and run outputs. A source-code commit is provenance, not a blanket reason to invalidate model work.

| Stage | Dependency identity | Reuse behavior |
| --- | --- | --- |
| Discovery / arbitration | Exact multimodal request (images, actual history, prompt, model, generation settings), endpoint, stage version | Reuse a schema-validated response when the request is identical. Different identity instructions, crop, history, or retry feedback can require new detection. |
| Crop description | Exact resized image and blind prompt, model, endpoint, generation settings | Editing the approved identity does not repeat this image-to-text call. |
| Identity comparison | Exact identity text, structured crop observation, prompt, model and endpoint | Changed identity reruns text comparison while preserving crop evidence. |
| Acceptance | Comparison evidence, threshold, verification schema, motion reliability/context, policy version | Threshold changes produce a new cheap decision, preserving the comparison. |
| Optical tracking | Previous image, next image, feature points, corners, box, accumulated uncertainty, OpenCV and tracker version | Restore the complete feature state on reuse; different seeds or directions must have matching actual inputs to reuse. Unreliable motion is a valid recorded outcome. |
| Camera path | Measurement arrays, leveling, anchors, source dimensions/cadence and framing settings | Reuse center/zoom arrays independently of Qwen. |

Batch jobs share `.batch/stage_records`. Standalone runs default to `<output>/.stage_records`; set `stage_store_dir` in their configuration to share a store. Relative configuration paths resolve relative to that configuration. Batch execution also supplies the shared store to jobs queued before this change. Replacing model weights behind the same endpoint/model name requires a new store namespace (`stage_store_dir`); the server does not expose a reliable weights digest.

Each stage has immutable `record.json` files addressed by SHA-256, with dependency fingerprints, result and creation time. Successful model records retain raw envelopes/responses and request audits. Exact discovery request audits include images: these records are local project data and can consume substantial storage. No retention/deletion policy is introduced here.

Per-key process locks prevent duplicate concurrent computation. Atomic publication ensures interrupted or failed calls cannot appear as completed records. Failed model output remains in diagnostic audits and is retried normally; it is never a reusable success. Schema-valid absence or rejected identity is valid evidence and is reused. Run-local `stage_usage.jsonl` references records and counts computations/reuses. Folder/Video-focus Progress shows these counts; they count requests, not unique frames. Reads consume only newly appended usage rows.

Run-local observations, optical diagnostics and scheduler checkpoints remain available for the existing UI. A matching scheduler checkpoint resumes directly. Changed scheduler inputs rebuild scheduling/selection and reuse matching stage evidence. Old combined detection caches are bypassed for stage-enabled runs so they cannot hide stale verification decisions. Existing completed runs are not rewritten or automatically migrated; the first new run populates the new store.

## What to expect when rerunning

- Same request in a new batch run: reuse model evidence across output directories.
- New description: reuse unchanged crop descriptions; recompute text comparisons and any discovery whose actual prompt/context changes.
- New acceptance threshold: reuse matching descriptions/comparisons; recompute policy and scheduling. Changed scheduling/history can legitimately introduce new discovery requests, so this is not a promise of zero model calls for a full analysis rerun.
- New optical algorithm: bump the tracker stage version. Existing discovery and crop records remain available; changed predicted crops require new descriptions.
- Output-only adjustment: use **Queue Rerendering (no re-analysis)**. It continues to run without Qwen. Camera-path records are separate; video encoding still runs again. `render_stage.json` records camera dependency and encoding completion.
- Explicit **Check against crops** / retry during description review remains a fresh comparison request, because the user asked for a new check; blind crop descriptions can still be reused.

## Validation and remaining optimization

Tests cover cross-run reuse, description/threshold/model invalidation, image/prompt invalidation, concurrent deduplication, immutable records, failed-call retry, and identical optical continuation after restoring cached state. Existing rendering tests exercise camera-stage integration.

Still separate follow-up work: migrate trustworthy legacy audits into records; add dedicated verification-only/reselection job actions; cache final encoded artifacts; avoid repeat tokenization on reused discovery; introduce storage retention. These are not prerequisites for the new shared evidence cache. No active job is restarted to install this change.

Camera-path version 2 constrains interpolated zoom using the rotated source and smoothed camera center: at least one complete output edge must lie inside the source image. Subject-fit limits also prevent excessive zoom-in when feasible. When full box visibility (including margin) conflicts with edge coverage, edge coverage takes priority unless the hard minimum crop short side would be violated; that minimum then wins with background fill. `zoom_constraints_conflict` flags the frame. Tracks record `zoom_min`, `zoom_max`, and the conflict; in a conflict these describe an infeasible interval. Feathering still affects the source boundary itself. Existing videos need rerendering to apply this behavior.

## Effective configuration at execution start

Configuration loading recursively merges nested project values over repository defaults. Module-resolved adaptive and anchor settings are materialized rather than left implicit. CLI and environment overrides are applied before the execution snapshot is saved.

Every newly started execution saves `effective_config.json` in its output directory. Immutable `execution_configs/*.json` records retain the start time, stage, code fingerprint/commit and complete resolved configuration for each attempt. `effective_config_record.json` points to the latest record. Analysis also writes `run_config.json`; rendering writes `render_config.json` after resolving actual output dimensions and the saved analysis cadence. Rerendering does not overwrite `run_config.json`.

Resolution happens at execution start, not enqueue time. Waiting jobs therefore use the defaults installed when they start; explicit snapshot overrides still win. Retries resolve again and append a new execution record, preserving prior attempts. Existing running processes and historical runs are not retrospectively assigned today's settings. The configuration panel uses recorded effective settings for batch runs when available. Values for stages not executed (such as tracking on a rerender-only job) are configuration values, not evidence that those stages ran.

Camera-path version 4 adds [log-zoom smoothing and look-ahead](ZOOM_SMOOTHING.md). The final zoom speed/fit requirements may relax complete-edge coverage, with explicit review flags and background fill.

## Scheduler event journal

Scheduler history is appended to `events_<id>.jsonl`, one compact JSON event per line. The candidate payload is unchanged. `anchor_checkpoint.json` now stores `event_journal: {version, file, committed_bytes, count}` instead of embedding history. Only pending events remain in memory; after a successful checkpoint they are cleared. Frame results and compatibility exports are unchanged.

Events are flushed and fsynced before atomic checkpoint replacement commits their prefix. On resume, a shorter-than-committed journal is an error. A longer tail represents an interrupted checkpoint: it is archived to `events_uncommitted_<id>.jsonl` and removed from the active journal before retrying the pending scheduler task. Committed events are never rewritten. Existing JSON checkpoints are backed up as `anchor_checkpoint.before_event_journal.json` and migrated once on resume; old journals are left untouched when a new analysis fingerprint starts a new run. This is process-crash recovery; the existing checkpoint writer does not guarantee durability across sudden power loss.

An already running process retains its loaded implementation until restarted. No active run files are migrated externally.
