# Reboot and interruption recovery

## Queue lifecycle

`action-reframe-queue.service` supervises the queue independently of the review UI.
It starts the configured model service, verifies its expected served model ID,
and continuously reconciles abandoned runners. OS locks establish liveness; saved
PID/status history does not. The service restarts on failure and starts with the
user's systemd manager (at boot when user lingering is enabled).

An abandoned starting/running job is marked interrupted. It is automatically
requeued only when its saved state passes recovery checks, the queue is enabled,
and its recorded executable fingerprint matches the current code. Real failures,
user stops/cancellations and deliberately paused queues are not automatically
retried. Recovered immediate renders enter the serial queue and obey its pause
setting. Historical interrupted jobs predating this feature do not become eligible
retroactively. Changing code blocks automatic recovery with an explicit error;
**Retry saved inputs** is the user's explicit opt-in to compatible stage reuse
under new code. New runs can adopt new defaults.

Each new execution freezes its fully resolved configuration in `resume_config.json`.
Retries use that configuration, including the endpoint, rather than new defaults.
Source file size/mtime and human labels are checked before processing. Compatibility
of expensive cached stages is decided by their dependency keys and stage versions.
No automatic silent migration of a changed analysis fingerprint is attempted during
same-code reboot recovery.

## Checkpoints and work loss

The scheduler commits at each existing operation boundary, including before and
after discovery/propagation. This is more frequent than a 30-second periodic save
when operations are fast. An in-flight model call may exceed 30 seconds; there is
no promise to recover an unfinished response. Successfully cached Qwen stages are
reused even if the scheduler had not yet committed the enclosing frame.

Checkpoint generations include scheduler state, result-shard references/checksums,
and a journal prefix boundary/checksum. File data is synced before replacement;
the directory is synced afterward. Five recent generations and up to 24 hourly
snapshots are retained alongside the previous checkpoint. Resume selects the
newest complete valid generation and never combines shards from different states.
Legacy files remain readable but cannot retroactively acquire missing checksums.

New journal checksums cover the committed prefix; trailing uncommitted bytes are
archived on resume. Referenced result shards and corruption archives are retained;
automatic shard garbage collection is intentionally not included because active
snapshot readers may still reference old generations. Monitor disk capacity.

Cache corruption causes evidence-preserving quarantine and recomputation under a
per-key lock. Crop/identity model results also pass their declared schema validator
before reuse, including legacy records without checksums. Storage/permission errors
remain visible failures; they are not silently converted into successes.

## Resumable rendering

The global camera plan is computed first. Focused and side-by-side videos are then
encoded in paired **30-second segments** (`render_segment_seconds`, configurable
in project JSON). Segment boundaries do not reset zoom, centering or leveling.
Each pair is decoded to verify frame counts/dimensions, hashed, synced and committed
with an atomic marker. Resume verifies the hashes and re-encodes only missing or
corrupt segments. Plan/source/output-setting changes select a different segment
cache. Encoder/compositor changes must bump `render_segments.VERSION`.

Final assembly stream-copies the video segments, maps source audio, and applies the
existing metadata policy. Assembly uses temporary files before replacement. If
assembly is interrupted, it repeats assembly, not segment encoding. The focused and
comparison videos are individually atomic, not an atomic pair; job success is
recorded only after both and the associated metadata finish. The standalone
`--stage compare` compatibility command remains a whole-video comparison encode;
normal render/all batch jobs use resumable paired segments.

Source timing retains the existing constant nominal FPS policy; variable frame-rate
timestamps are not newly preserved. A segment commit limits repeated encoding to
at most one segment pair in normal interruption cases, not 30 seconds of wall time.
Global camera planning, metadata export and final assembly may still repeat after
an interruption. This does not provide replication or protection against total
disk loss. Keep original media and user labels backed up.

## UI and verification

The folder run list shows recovery messages, restored checkpoint result/coverage
counts, encoding phase, completed frames and reused segment counts. Logs retain
full tracebacks. Tests include actual SIGKILL during simulated model computation
and before atomic replacement, failed checkpoint commits, corrupt cache/shards,
bounded checkpoint history, disk-full sync failure, supervisor recovery with pause
and code-version safeguards, interrupted encoding/assembly, segment reuse and
fractional-FPS/audio continuity. These exercise software failure boundaries; they
do not simulate every hardware/filesystem power-loss behavior.
