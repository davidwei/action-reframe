# Lookout — operating guide

Open **/lookout** from Folder view or Video focus. This first release generates a
local daily report with up to three UX suggestions and three operational
suggestions, without scores. Fewer suggestions mean insufficient evidence, not a
broken report. See the [project plan](LOOKOUT_PLAN.md) for the design.

## What is available

- Browser activity buckets (movement exists, never coordinates), action IDs,
  text-edit lengths/durations (never contents), coarse scrolling/control visibility,
  playback/seek groups, drawing duration, write-request latency/outcomes and UI errors.
- Nonblocking local event transport, bounded payloads/buffers, one collector,
  separate SQLite/WAL storage, event deduplication and schema validation.
- Processing-stage spans, model request latency/token counts, preparation cache/seek
  counters and optical update counters for newly started instrumented runners.
- Five-second process CPU/memory and NVML GPU utilization/memory/power samples.
  GPU support is optional. These are shared device samples, not per-request GPU time.
- Queue transitions and explicitly labeled historical snapshots. Existing jobs do
  not acquire previously unrecorded stage/model history merely by deploying Lookout.
- Evidence drill-down, Markdown download, event export, collection settings,
  explicit manual deletion, persistent select/defer/dismiss/reopen decisions.
- Optional Qwen commentary requested from the report page when video jobs are idle.
  The deterministic report does not depend on Qwen. Selecting a recommendation
  never implements it automatically.
- Independent user service with crash restart, minute-level report refresh, daily
  generation at the configured hour (default 07:00 America/Los_Angeles), and
  catch-up for missing days. Today's report is provisional. No automatic retention.

The initial recommendation rules are deliberately transparent hypotheses, with
counts and uncertainty rather than causal claims. Dismissed/selected opportunities
are suppressed until reopened. Defer requires a date. Saved report content is
refreshed when decisions change or when the user requests Refresh evidence.

## Install and verify

Use the repository's dedicated environment, not a robotics environment:

```bash
.venv/bin/python scripts/install_lookout_service.py --workspace /path/to/videos
# Review the printed service first, then install:
.venv/bin/python scripts/install_lookout_service.py --workspace /path/to/videos --install
systemctl --user status action-reframe-lookout.service
journalctl --user -u action-reframe-lookout.service
```

The service executes the collector from this checkout. User lingering must already
be enabled if collection should survive logout; the installer does not alter
account policy. Linux Unix datagrams, `/proc`, and user systemd are used for this
initial deployment. Paths and interpreter are generated from arguments; no account,
GPU count, or model endpoint is hardcoded. The installer preserves virtualenv paths.

The HTTP application must run this version to expose `/lookout`. Refresh open
browser pages to load its collector. Existing analysis runners keep their loaded
code; new runners automatically configure Lookout's workspace/job identity.
Standalone integrations may set `LOOKOUT_WORKSPACE` before calling instrumented
code. Restart only the collector to deploy collector/report changes; restart the
review server for HTTP changes, preserving active runners.

Data lives under `<workspace>/.lookout/`, ignored by Git. Disable collection before
manual deletion and wait for the collector to acknowledge it. Deletion removes
events, saved reports and decisions, but retains job-status bookkeeping so old
queue snapshots are not immediately re-imported. No video, project or job is deleted.
Collection status reports dropped/rejected events and database/control-file size.
Export streams newline-delimited events rather than loading the full store into RAM.

## Interpretation and limits

- Active time is an estimate based on a visible/focused page, a 60-second idle
  cutoff, and 30-second buckets. Concurrent tabs use the maximum activity per bucket;
  multiple simultaneous people cannot be identified from sessions.
- A text edit ending without a save at that moment is not proof of lost work.
  Suggestions explicitly ask for validation. Click-to-task outcomes are linked by
  action IDs, but overlapping actions and asynchronous UI behavior can be ambiguous.
- Inclusive stage CPU/wall times can overlap; do not sum them as exclusive costs.
  GPU resource metrics are device-wide; different GPUs/processes may be mixed in
  summary distributions. Raw events retain the device index/job where available.
- Micro-operation breakdowns (encoder versus blending, disk I/O attribution,
  encoder/decoder GPU utilization, per-request GPU execution time), precise
  multi-user attention attribution, and completed before/after product experiments
  need further instrumentation/evidence. No values are invented for them.
- Current session telemetry cannot reconstruct older user activity. Historical
  queue snapshots are separately labeled; no UX recommendations are invented to
  fill all three slots. Newly successful recovery changes may remove old issues.
- Browser buffers cap at 200 events; uploads cap at 50 events/64 KiB. Unix datagrams
  and collector queues are bounded; loss is preferable to blocking processing.
  Producer-side drops are reported on a later successful send; permanent outages
  can leave unmeasured loss. Collector gaps and this limitation must be considered.
- Telemetry is local instrumentation, not an access-control boundary. The existing
  loopback-only app and same-origin write protection still apply.

## Validation at first deployment

Python tests cover schema rejection, deduplication, DST day boundaries, persistent
recommendation decisions, disabled-collection deletion, unavailable transport,
and overlapping activity buckets. Browser checks verified the real daily report,
selection persistence, action collection, and the page-exit beacon using an
isolated workspace for mutations.

A six-pair local microbenchmark of 350 repeated 720p warp/blur operations measured
median 0.46849 s without per-frame counters and 0.46883 s with them: +0.073%.
Individual paired differences ranged from -1.72% to +0.73%, so the result is within
measurement variability. An unavailable collector cost approximately 9 microseconds
per attempted event. This supports the lightweight path but is **not** a complete
long-video throughput benchmark or proof of every workload's <1% target. No active
production video was restarted for benchmarking.
