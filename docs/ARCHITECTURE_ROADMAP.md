# Architecture and next steps

The agreed architecture is **four core components → video-level scheduler → folder-level workflow**. Leveling and rendering support the output; they are not additional tracking components. See [current approach](CURRENT_APPROACH.md) and [video processing paths](TWO_PATH_TRACKING.md) for implemented behavior.

## Built versus remaining

| Owner | Built | Remaining feature work |
| --- | --- | --- |
| C1: Human labeling | Polygon labels in raw/transformed views, estimate approval, absence, crop-based draft descriptions, explicit checks/approval, description revisions | Reliable propagation of edits into live work; more efficient batch annotation |
| C2: Verification | Shared blind crop description/text comparison, identity/localization distinction, partial/blur tolerance, positive and absent reference checks | Calibrated evaluation set and richer geometric validation |
| C3: Independent detection | Raw/leveled Qwen localization, verified evidence, bounded output-error retries and request audits | Selective region repair and better recovery across difficult scenes |
| C4: Motion tracking | Separate raw/leveled optical states, per-frame proposals, periodic verification, unverified motion retained for rendering | Alternative tracker adapters and better scene-cut/occlusion handling |
| Video scheduler | Bidirectional seeds, unresolved-region discovery, bounded attempts, checkpoints, reusable stage records, three-cadence progress | Dedicated verification-only jobs and targeted interval reprocessing |
| Folder workflow | Library states, approved input snapshots, serial durable queue, rerender priority, stop/retry, old successful result retention | Planner/trial/production approvals, recursive import, execution-time stale-input checks |
| Output/review | Gyro leveling, independent visual comparison, constrained smooth zoom, feathered borders, synchronized review, metadata sidecars | General camera/visual leveling adapters, segment selection/export, optional enhancement |
| Operations | Lookout daily suggestions, activity/error telemetry, configuration/code provenance | Managed review/queue deployment, capacity controls and broader reliability validation |

## Next feature deliveries

Each step should produce a user-verifiable result; do not treat an old milestone heading as evidence of completion.

1. **Targeted reruns:** choose verification-only or an interval repair, preserving compatible detection/optical evidence. Verify the stage-reuse counters and unchanged unrelated results.
2. **Input freshness:** explicitly resolve edited labels/descriptions/settings before execution or resumption. Verify that a queued job either uses its visibly approved snapshot or requires a new approval; never silently substitute inputs.
3. **General leveling:** add validated telemetry adapters and gyro-free horizon/scene estimation. Verify representative sailing, open-ocean and ski clips with uncertainty visible.
4. **Planner and trial workflow:** prepare representative frames/instructions, edit a proposed plan, run trials offline, approve production separately. Verify a rejected trial cannot silently become approved production.
5. **Final selects:** mark useful intervals and export them with provenance. Verify timestamps, synchronization, metadata and preserved original outputs.

## Optimization work

Optimize within the same architecture, using fixed clips and observable outcomes:

- C1/folder: reduce navigation, repeated labeling and recovery actions. Use Lookout's top-three UX and operational suggestions without ranking scores.
- C2/C3: measure wrong-subject acceptance, missed targets and box placement, not just increasing model confidence. Compare prompt changes on both positive and absent examples.
- C4/video: tune motion and verification cadences independently; compare coverage, drift, model calls and human corrections.
- Processing: profile decoding, model calls, optical flow and encoding before adding GPU acceleration or concurrency. Verify both elapsed time and output equivalence.
- Operations: exercise interruption, resume, malformed outputs and service outages; measure manual interventions and preserved work.

The [original project plan](PROJECT_PLAN.md) and [design](PROJECT_DESIGN.md) remain the broader product vision. Their original ordering/status descriptions are historical, not the current implementation ledger.
