# Performance, reliability and operations improvements

This document records the implemented baseline and the next engineering improvements.
It preserves the agreed architecture: C1 human labeling, C2 verification, C3 independent
detection, C4 motion tracking, V video-level scheduling, and F folder-level workflow.
These are improvements within those components, not new architecture layers.

Status: 2026-09-27, following commit `196058e`. “Implemented” describes repository
behavior; deployment details and running process IDs can change. Proposed work below
has not been implemented merely by being listed here.

## Implemented baseline

| Area | Current behavior | Remaining limitation |
| --- | --- | --- |
| Analysis cost (C3/C4/V) | Optical tracking, confidence-driven anchor expansion, unresolved-region discovery, configurable analysis cadence, bounded image context and cached model work | Model verification can still dominate runtime; no measured end-to-end performance baseline |
| Description checks (C1/C2) | Shared blind crop descriptor and text comparator; cached observations reused for summary retries and edited-text checks | Scores are model judgments, not calibrated probabilities; full-frame negative checks do not test every possible candidate crop |
| Negative examples (C2) | Human-marked absent frames are checked without revealing their labels to the descriptor/comparator; positive expectation ≥80%, negative expectation ≤20% | These review thresholds do not establish detection precision/recall or change the tracking threshold |
| Zoom (V) | 1× endpoints and linear magnification between confident-box anchors; gaps no longer trigger zoom-out | Zoom speed can change at anchors; dense, noisy confident boxes can still cause fluctuations |
| Rerendering (F) | Saved analysis and corrections copied into a separate run; render-only stage performs no Qwen requests | Decoding, image processing and encoding are currently CPU work |
| Queue scheduling (F) | One shared serial queue; rerenders before waiting analysis jobs; FIFO within each group; no preemption | A sustained stream of rerenders can delay analysis; no fairness policy or concurrent render lane |
| Job durability (F) | SQLite queue, saved input snapshots, separate output folders, worker/run locks, explicit failure and interrupted states | Persistent queue state does not itself keep a process alive or restart it |
| Recovery (F) | Start/resume reconciles stale running state; retries reuse saved inputs and applicable caches; failed jobs do not block later jobs | No guarantee of exact-frame render resume; no automatic bounded transient-error retry policy |
| Provenance (V/F) | Recording/camera tags in new exports; metadata sidecar, original data-packet archive and frame transforms | Not a complete archive of all proprietary container metadata; moving runtime caches is not generally supported |
| Review operations (C1/F) | Folder states, last-update dates, per-run logs, corrections, side-by-side comparison, archive/restore | Limited live stage timing, health diagnostics and resource visibility |

The most recent completed suite contained **84 passing tests**, including synthetic
media integration tests and an unavailable-model-endpoint rerender test. Browser
checks covered rerender priority display and absent-frame feedback. These verify
behavior; they are not performance benchmarks or real-model quality measurements.

## Performance improvements

| Priority | Work | Owner | Result to verify |
| --- | --- | --- | --- |
| P1 | Instrument and benchmark the current pipeline before changing backends | C2–C4/V/F | One report separates model wait/inference, decoding, measurement, transform/composite, focused encoding, comparison generation and telemetry archival time |
| P2 | Add configurable NVENC encoding for focused and comparison videos, with CPU fallback | F | Same saved analysis renders with both backends; report total wall time, encoder time, output size, quality and fallback reason |
| P3 | Move rotation, scaling, blur and compositing to GPU if P1/P2 identify those operations as bottlenecks | V/F | Identical source frames and transforms produce geometrically equivalent results, including feathered borders and protected subject pixels |
| P4 | Add NVDEC decoding and keep frames on the GPU where practical | V/F | Show reduced decode/transfer cost and an end-to-end improvement; verify frame order, timestamps and audio synchronization |
| P5 | Tune model scheduling and verification frequency using fixed labeled clips | C2–C4/V | Better verified coverage per model call/time without increasing drift, identity switches or false accepts |
| P6 | Evaluate a separate render execution lane while retaining one logical queue | F | Analysis and render coexist without out-of-memory failures or unacceptable slowdown; compare combined throughput with the serial baseline |

The current bundled FFmpeg exposes no NVENC encoders, and the installed OpenCV reports
no CUDA devices. GPU encoding is therefore not a configuration switch in the current
installation: dependencies and renderer code need changes. Hardware support must be
probed at runtime on each deployment; retain a portable CPU path.

Start GPU work with encoding because it requires less pipeline restructuring. NVENC
and NVDEC use dedicated video engines, while GPU image transformations use compute
resources. That separation does not guarantee contention-free operation alongside
Qwen: memory capacity, bandwidth, transfers, CPU and storage still matter. Do not
promise a speedup or increase concurrency before measuring it. Use NVIDIA's
[FFmpeg integration documentation](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)
when implementing the backend.

### Benchmark protocol

Use the same source interval, saved analysis, labels and rendering settings for every
render comparison. Record input resolution/FPS/duration, output settings, source and
analysis revision, code commit, dependency/driver versions, selected GPU, codec,
quality settings and whether analysis is concurrently running. Compare quality at
comparable settings; CPU CRF and GPU quality controls are not numerically equivalent.

Measure cold and warm runs separately. Report total wall time, rendered frames/second,
per-stage time, peak RAM/VRAM, CPU/GPU utilization, output size, failures and retry cost.
Include focused and side-by-side generation plus metadata archival in total time.
Compare source/audio duration, representative output frames, box containment and
border behavior. No speedup target is claimed until this baseline exists.

For analysis experiments, add model calls, prompt tokens/image counts, request latency,
queue wait, verified coverage, identity switches, false accepts/rejects and human
correction effort. Keep evaluation labels separate from reference images supplied to
the model; include blurry targets, lookalikes, absent frames, occlusion, reappearance,
open ocean and skiing as footage becomes available.

## Reliability improvements

1. **Manage process lifetime independently of interactive sessions (F).** Run the UI
   and worker under a service manager. Verify reboot, logout, UI restart and worker
   restart without duplicate dispatch. Inference service availability must be checked
   separately; managing the queue does not manage vLLM automatically.
2. **Strengthen recovery and observability (F).** Add heartbeats, last-progress times,
   bounded transient-error retries and clear stalled-job diagnostics. Distinguish slow
   model requests from dead runners. Demonstrate scheduler loss, runner loss, unavailable
   inference, invalid responses and disk-full failures. Preserve prior valid outputs.
3. **Make resume/invalidation contracts explicit (C2–C4/V/F).** Record model identity,
   prompt/schema versions, source identity, analysis provenance and render backend in
   run manifests. Reuse only compatible artifacts. Explain which input changes require
   re-description, re-analysis or rerendering. Verify label edits and model/prompt changes
   cannot silently reuse stale confidence results.
4. **Validate alternative rendering backends (V/F).** Establish geometric checks for
   rotation sign, coordinate transforms, crop containment and borders. Check output
   frame counts, A/V synchronization, metadata, and encoder failure handling. A CPU
   fallback must be visible in the run record, not silently presented as GPU success.
5. **Calibrate verification independently (C2).** Evaluate positive/negative scores
   against human judgments rather than optimizing agreement among model-generated
   texts alone. Keep identity confidence, completeness and localization quality separate.
   Do not rewrite labels or force model scores to satisfy expected thresholds.
6. **Add storage lifecycle controls (F).** Estimate required output/cache space, surface
   disk pressure, and provide explicit retention/export/cleanup operations. Back up queue
   state together with configurations, labels and manifests. Test restore into a fresh
   workspace; archive/discard must continue to preserve user media unless deletion is
   explicitly requested.

## Operating model and service improvements

### How it runs today

The review server, queue worker and current job runner are separate Python processes
using the configured project's virtual environment and the launching OS account.
Start/resume launches a detached worker. Closing the browser or finishing a Codex turn
does not inherently stop processing. The worker exits when paused or when no queued
jobs remain; after it has exited, new jobs require Start/resume.

The inspected deployment was launched from an interactive terminal and remained in
that terminal's systemd scope despite detached process sessions. It is **not an
installed, supervised service**. Logout/scope termination, reboot and process crashes
must not be assumed to recover automatically. Queue records survive in the workspace,
but an operator must restart the processes and reconcile interrupted jobs.

### Proposed service deployment

Use configurable service definitions, not hardcoded usernames or machine paths. On
Linux, choose either a system service with an explicit unprivileged `User`, or a user
service with lingering enabled if it must run without login. Keep repository code,
Python environment, workspace, port and model endpoint configurable. Continue binding
the UI to loopback unless a separately designed access-control setup is introduced.

Manage UI and worker separately. Before enabling automatic worker restart, add an idle
wait/notification mode: blindly applying `Restart=always` to today's exit-on-empty
worker would create a restart loop. Preserve the persisted pause flag. Define explicit
start, stop, graceful shutdown, restart and drain behavior; ensure the service manager's
process-group policy does not accidentally kill a runner during scheduler-only reloads.
On crash/reboot, reconcile locks and job states before dispatching new work.

Operator-visible improvements should include:

- Service/worker/model health, execution backend, selected GPU, last progress and log links.
- Stage timing and useful render progress instead of analysis-oriented waiting text.
- Queue ordering that matches dispatch: running job, FIFO rerenders, FIFO analysis jobs.
- Clear explanations for blocked jobs, fallback, retry, source changes and stale approvals.
- Versioned deployment, log rotation, diagnostics export, backup/restore and upgrade rollback.

Keep serial execution initially. If a concurrent render lane is later added, it should
remain part of the same logical queue and preserve job-type priority. Define fairness
(e.g. aging) only if rerender demand demonstrably starves analysis; the current agreed
policy is strict rerender priority without interruption of active work.

### Current operator procedure

1. Launch the review server with the desired workspace using `scripts/run_review.sh`.
2. Open `/library`, prepare/approve analysis projects or queue rerenders from saved analysis.
3. Select **Start / resume queue**. Use **Pause after current video** to stop later dispatch.
4. Inspect progress and job logs. Review outputs, save corrections, then queue a rerender
   or a new analysis revision as appropriate.
5. After an unexpected shutdown, restart the UI and select Start/resume to reconcile
   interrupted work. Retry the desired interrupted job and start the queue again if idle.

Runtime locations are relative to the selected workspace: `.batch/queue.sqlite3`,
`.batch/worker.log`, `.batch/runs/<id>/` and `outputs/batch/<id>/job.log`. Do not move or
edit active run snapshots. See [batch workflow](BATCH_WORKFLOW.md) for exact behavior.

## Recommended delivery order

| Step | Deliverable | Acceptance check |
| --- | --- | --- |
| 1 | Stage timing and reproducible baseline report | Repeat one analysis and one saved-analysis render; distinguish cache reuse from actual acceleration |
| 2 | Worker idle mode and managed UI/worker services | Logout/reboot/restart tests; one active runner; persisted pause respected; no restart loop |
| 3 | GPU encoding with explicit CPU fallback | Both videos produced, metadata/audio retained, backend recorded, measured speed/quality comparison |
| 4 | Recovery/health dashboard and transient-failure policy | Inject failures and verify clear state, bounded retries and intact prior results |
| 5 | GPU frame processing and decoding if justified | End-to-end benchmark improves while geometry, borders and synchronization remain correct |
| 6 | Resource-aware concurrent rendering if justified | Higher combined throughput without analysis quality loss, memory exhaustion or duplicate execution |
| 7 | Storage retention, backup/restore and maintenance runbook | Restore a workspace and its queue on a fresh installation; preserve source media and provenance |

Commit and push each completed, tested increment. Record benchmark artifacts and
limitations with the relevant implementation commit. Keep private footage, generated
outputs, environments and secrets out of Git.
