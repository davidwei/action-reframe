# Lookout — project plan

Status: proposed; this document does not imply telemetry is implemented.
Date: 2026-09-28.

**Observe the work. Find the friction. Suggest the next improvement.**

## Goal and decisions

Lookout identifies opportunities to reduce human attention required by Action
Reframe: both interaction effort and operational interruptions. It provides
recommendations for the user to choose, not automatic product changes.

The daily deliverable is **up to three UX improvements and up to three operational
improvements**. There are no scores, weighted formulas, numeric priority ratings,
or composite rankings. If evidence supports fewer suggestions, show fewer.
Machine speed matters when it reduces waiting, checking, intervention, or rework;
unattended compute time alone does not determine the recommendations.

Distinguish necessary attention (reviewing an ambiguous target) from potentially
avoidable attention (restarting after malformed model output). Measurements do
not by themselves prove frustration, confusion, or causality.

Lookout is a supporting capability in this repository, not a replacement for the
four-component tracking architecture. See [architecture](ARCHITECTURE_ROADMAP.md),
[folder workflow](BATCH_WORKFLOW.md), and
[performance and operations](PERFORMANCE_RELIABILITY_OPERATIONS.md).

## User experience and daily report

Add a Lookout page linked from Folder view. Its landing view is the daily report,
with a date selector, collection coverage, and these two lists:

- **Top 3 UX improvements:** labeling, navigation, review, editing, and feedback.
- **Top 3 operational improvements:** recovery, queue/service reliability,
  troubleshooting, status checking, and repeated processing.

Every suggestion contains:

| Field | Required content |
|---|---|
| Problem | Concrete source of unnecessary attention |
| Evidence | Observed actions/incidents, sample size, time window, and representative project/job links |
| Proposed change | A specific feature or optimization |
| Expected benefit | How it could reduce effort or interruptions; label estimates explicitly |
| Uncertainty | Alternative explanations, missing data, and hypotheses |
| Verification | A before/after measure plus quality or reliability guardrails |

Actions: **Select for implementation**, **Defer**, **Dismiss**. Selection records
an intention; it does not edit code, start work, contact anyone, or change jobs.
Allow an optional reason and retain decisions across reports. Merge recurring
issues into one opportunity; do not repeatedly promote dismissed suggestions
without materially new evidence. Deferred items can be revisited on the selected
date. Selected items remain visible with implementation/verification status.

Expanding a suggestion shows a workflow or job timeline and supporting counts.
Raw event inspection is secondary. Do not default to a wall of resource charts.
Show active effort, waiting, and unattended processing separately. Before/after
comparisons must account for version, configuration, video length/resolution,
cache state, and task difficulty; small samples require explicit uncertainty.

## Initial hypotheses from our discussions

These are starting hypotheses, not findings established by telemetry.

| List | Opportunity | Evidence to collect |
|---|---|---|
| UX | Explain preparation and current progress clearly | Status shown, progress freshness, repeated visits/refreshes, preparation duration |
| UX | Keep review/approval controls beside the video | Section transitions, coarse scrolling, control visibility, actions per corrected frame |
| UX | Distinguish source projects, saved runs, and next-run settings | View identity, disabled-action attempts, navigation to editable source, repeated setting changes |
| Operations | Recover from model-output failures without intervention | Retry outcomes, skipped/reviewed failures, manual restarts, successful alternate paths |
| Operations | Make overnight processing unattended | Queue pickup, worker availability, stalls/restarts, human recovery actions |
| Operations | Preserve useful work on stop/retry and improve preparation | Cache/checkpoint reuse, invalidation causes, repeated decoding, time before analysis |

Some related fixes already exist (Stop processing, bounded crop retries, and
frame-failure review). Lookout should measure remaining friction and verify those
fixes, rather than recommend already-shipped behavior as if it were missing.

## Telemetry contract

Use versioned events with an event ID, UTC timestamp, event type, software version,
and optional session, workflow, action, project, job, and configuration revision
IDs. Use monotonic clocks for durations within a process. Server receipt time is
separate from client time; tolerate clock skew and duplicate delivery. Link an
action to its API outcome and resulting job without pretending their durations
are additive. Project/job references resolve locally to existing review pages.

Stable semantic action IDs (for example `label.approve_leveled`,
`description.draft`, `job.stop`) are preferable to DOM labels or CSS selectors.
Validate against an allowlisted schema, bounded field sizes and batch limits.
Aggregate events by actual workflow outcome, not just clicks.

### UX events

| Event family | Collected details | Purpose |
|---|---|---|
| View/section | Folder/focus/comparison, labeling/descriptions/output, source versus snapshot, enter/leave | Workflow navigation and view confusion |
| Activity interval | Visible/focused state, mouse-movement-exists flag, keyboard-activity-exists flag, active seconds | Approximate attention, excluding unattended tabs |
| Action | Semantic button ID, section, enabled state where observable, outcome, action ID | Repeated work, common actions, unsuccessful interactions |
| Label operation | Draw/adjust/approve/absent/save, duration, result, frame reference | Effort per reviewed or corrected frame |
| Text-edit session | Field ID, start/end, length change, save/abandon outcome | Description rework and save clarity |
| Navigation | Coarse scroll occurrence, section transitions, key-control visibility, grouped seeks | Control placement and inspection friction |
| Playback | Play/pause, buffering duration, preview failures | Waiting during review |
| Request/UI error | Endpoint action category, duration, structured failure category | Failed saves and missing feedback |
| Status check | View revisit/refresh during processing, displayed stage and freshness | Repeated checking and unclear progress |

Do not log every mousemove, keypress, scroll event, or slider update. Disabled
native buttons do not reliably emit clicks: use an explicit observable wrapper or
help action if needed, and never infer attempts from unavailable events.

Active-time accounting must exclude hidden tabs and inactivity; avoid double
counting concurrent tabs. Treat reading time and activity-based estimates as
imperfect, and disclose the idle cutoff. Initial proposal: 60-second inactivity
cutoff and 30-second activity buckets. Report wait time only when a visible,
initiated action is pending; distinguish it from active interaction time.

### Processing and service events

| Area | Collected details |
|---|---|
| Job lifecycle | Queue/start/stop/failure/interruption/retry/completion, reason, initiating action |
| Stages | Probe, preparation, metadata/leveling, discovery, propagation, verification, render/export; start/end and last progress |
| Preparation | Decoded/cached frames, seek count, throughput, bytes written, cache hits |
| Model calls | Purpose, frame/path, latency, input/output tokens, finish reason, retries, outcome, model ID |
| Tracking | Discovery results, optical updates, losses, verification outcomes, unresolved frames; aggregated counters |
| Recovery | Automatic recovery, failed-frame review, preserved alternate path, human intervention |
| Reuse | Cache/checkpoint reuse and invalidation reasons, work repeated |
| Render/export | Decode/transform/encode/audio/metadata timings and throughput |
| Resources | Process CPU time/utilization, memory, disk I/O; GPU utilization/memory/power and encode/decode utilization when available |
| Services | Heartbeats, worker start/exit, queue pickup delay, stalls and model-server availability |

Request latency includes queueing and is not GPU execution time. GPU samples are
shared device measurements; do not assign them as exact per-request GPU time.
Process CPU deltas are also shared across concurrent threads. Explicitly mark
exclusive versus overlapping durations and unavailable metrics. Detailed kernel
profiling is an opt-in benchmark tool, not always-on telemetry.

## Architecture and overhead budget

1. **Browser collector:** delegated action listeners and in-memory aggregation;
   correlate actions with the shared API wrapper. Flush every 15 seconds or 50
   events; use `sendBeacon` on page exit. Bound buffers and payloads; no synchronous
   network or storage on interactions. Sample/coalesce high-frequency events.
2. **Application instrumentation:** lightweight spans around expensive operations;
   one event per Qwen request, aggregated optical/render work every five seconds.
   Prefer instrumenting central request wrappers to duplicating each call site.
3. **Collector:** bounded asynchronous ingestion and batched writes to a separate
   SQLite database in WAL mode, never the queue database. Across processes, use a
   bounded local transport to a single writer; unavailable telemetry must not block
   the caller. Measure dropped events and rejected/duplicate batches.
4. **Resource sampler:** one collector samples at five-second intervals; prefer
   persistent GPU metric interfaces over repeatedly launching external commands.
5. **Daily aggregator/reporter:** deterministic statistics first; optional model
   narration from aggregates only. Run outside latency-sensitive processing and
   defer model narration behind video jobs. The report remains available without
   the model. Use the configured local timezone and handle DST boundaries.

Proposed starting limits: browser buffer 200 events / 256 KiB, upload batch at most
50 events / 64 KiB, backend queue 10,000 events / 16 MiB. Define an overflow policy
that preferentially retains errors/lifecycle events but never blocks processing.
These are tunable engineering limits, not user-priority scores.

Acceptance target: less than 1% processing-throughput degradation on representative
repeated benchmarks, with measurement noise reported. Check UI latency and memory
as well. Telemetry disk-full, collector loss, and invalid payloads must never fail
a label save, playback, or an analysis job. Report gaps instead of presenting
partial counts as complete.

## Privacy, portability, and retention

Default to local-only collection. Do not collect mouse coordinates/trails, text
contents, keystrokes, images, raw model prompts/responses, filenames, or full URLs.
Use bounded error categories plus links to existing local diagnostics, rather than
copying potentially sensitive exception bodies into telemetry. Record random
session IDs; persistent personal identity is not needed initially. Do not infer
unique people from browsers or sessions.

Expose collection status and enable/disable, export, and delete controls. Suggested
retention: 30 days of detailed events and one year of daily aggregates. Keep all
paths under a configured workspace; no hardcoded account, GPU count, model endpoint,
or machine path. Missing GPU support should reduce available metrics, not fail the
collector. Daily scheduling must be owned by a service/timer independent of Codex
or a browser tab; include catch-up generation after downtime.

## How daily recommendations are produced

Build deterministic workflow funnels and incident summaries, then identify recurring
unnecessary attention. Separate observations from interpretations. Prefer issues
causing interventions, repeated effort, or checking; resource cost alone does not
justify promotion. No scores or formulas are generated or displayed.

For each list, choose up to three distinct, actionable opportunities, explaining
why they merit attention. Include evidence counts, collection gaps and sample size.
Avoid duplicated UX/operations recommendations unless their proposed changes are
meaningfully different. Optional model commentary must reference evidence IDs;
validate the report schema and evidence references. If narration fails, show the
statistics and deterministic candidates without invented recommendations.

## Step-by-step delivery

Each step produces an independently reviewable result. Commit completed steps;
keep telemetry data out of source control.

| Step | Deliverable | User-verifiable result / acceptance |
|---|---|---|
| 1. Event contract and fixtures | Schemas, action vocabulary, sample workflows, configurable limits | Inspect example records: no text/image/coordinate leakage; normal activity and failure cases are represented |
| 2. Collector and controls | Separate store, bounded ingestion, retention, collection status/export/delete | Enable/disable collection; duplicate/invalid batches handled; collector outage and full buffers do not affect app operations |
| 3. UX instrumentation | Labeling, description, navigation, playback and job-control events | Perform one project-preparation and one failed-frame correction workflow; inspect their action timelines and outcomes; hidden tabs do not accumulate active time |
| 4. Processing instrumentation | Timed stages, model calls, reuse/recovery, resource samples | Run a short video; reconcile stage timeline with job elapsed time; retries/cache hits visible; GPU attribution limits explicit |
| 5. Daily aggregates | Workflow effort, interruptions, waiting/checking, incidents and comparison cohorts | Generate a report from fixtures with known totals; verify timezone boundaries, dropped data, overlapping tabs and overlapping spans |
| 6. Lookout daily view | Two lists, drill-down evidence, select/defer/dismiss and persistent decisions | Review up to three items per list with no scores; select one without triggering implementation; dismissed items stay dismissed absent new evidence |
| 7. Optional narrative and scheduling | Aggregate-only model input, independent daily timer, deterministic fallback | Report appears with browser closed; missed days catch up; model outage still yields a usable report |
| 8. Overhead and improvement validation | On/off benchmarks, retention/load/fault tests, before/after example | Demonstrate overhead budget, bounded storage/memory, uninterrupted app behavior under telemetry failure, and evidence for one completed optimization |

## First-release boundary

The first release collects lightweight evidence and produces actionable daily
suggestions. It does not implement session replay, individual employee analytics,
automatic code changes, external notifications, exact per-request GPU profiling,
or an opaque prioritization engine. Its success is whether the user can choose
useful improvements with less investigation—not how many events it collects.
