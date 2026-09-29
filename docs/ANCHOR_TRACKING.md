# Video-level scheduling

This is the current scheduler for new `anchor` and `dual` analyses. The [two-path guide](TWO_PATH_TRACKING.md) defines geometry, branch seeds and candidate selection. Explicit `single` mode and saved older runs retain legacy behavior.

1. Load authoritative human boxes/absence, gyro attitude, settings and compatible saved checkpoints.
2. Seed forward and backward propagation from human labels. Each branch maintains its own optical state; directions visit neighboring source frames in traversal order.
3. Propagate at source FPS and verify predicted crops at scheduled checkpoints. Retain reliable motion even when identity verification fails; do not promote it to an independent anchor.
4. Recover each lost/unverified branch independently on the discovery grid, at no more than 2 FPS per branch. Keep both optical and independent proposals when both exist.
5. Accepted independent detections can seed propagation in either direction even below the high-anchor threshold. High-confidence, independently localized detections receive anchor priority. Human absence stops propagation through its frame.
6. When propagation tasks are exhausted, scan unresolved, previously unscanned discovery positions. New detections can restart propagation. Bound repeated attempts and finish when no scheduled work remains.
7. Render from saved candidates and corrections; analysis never applies zoom.

## Progress and failures

The three coverage counters are unique discovery positions, crop-verification positions, and optical source frames. Attempts may exceed unique counts because of paths, directions and retries. Adaptive completion does not require every counter to reach its denominator. Medium/high counts use acceptance policy, not motion quality; high is a subset of medium-or-higher.

The overnight queue highlights a stage title while the worker reports executing that operation. Discovery includes independent localization; crop verification includes description and text comparison; optical tracking covers motion updates. UI polling can miss brief transitions. Workers started before activity instrumentation do not report an active title. Finished/failed/stopped jobs do not retain an active highlight.

Recognized malformed/truncated model-output failures are saved for frame review rather than treated as confident absence. Valid alternative evidence and successful history remain available. Transport/service failures can still stop the job. Compatible checkpoints and [stage records](STAGE_RECORDS.md) reduce repeat work; changed dependencies may require recomputation.

## Implementation

- [Scheduler](../src/analysis_scheduler.py): work order, directions, coverage and bounded attempts.
- [Run orchestration](../src/anchor_tracking.py): configuration, gyro, checkpoints and output publication.
- [Two-path execution](../src/two_path_tracking.py): independent branch states, motion, verification and recovery.
- [Candidate policy](../src/path_candidates.py): eligible winners and render selection.
- [Progress](../src/tracking_progress.py): coverage, confidence counts and current operation.
