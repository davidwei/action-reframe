# Documentation guide

Start with [Current approach](CURRENT_APPROACH.md) for the goal, tradeoffs and implemented behavior. [Architecture and next steps](ARCHITECTURE_ROADMAP.md) separates working features from remaining work.

## Current implementation

- [Adaptive verification and crop limits](ADAPTIVE_VERIFICATION.md): evaluation/opt-in modes, tiny crops, linked thresholds and rendering constraints.

- [Video processing paths](TWO_PATH_TRACKING.md): independent raw/leveled branches, coordinates, three processing cadences, seed selection and rendering selection.
- [Video scheduler](ANCHOR_TRACKING.md): bidirectional propagation, discovery, failures and progress.
- [Verification policy](VERIFICATION_POLICY.md): identity, localization and human authority.
- [Stage records](STAGE_RECORDS.md): reusable evidence and rerun boundaries.
- [Folder workflow](BATCH_WORKFLOW.md): preparation, approval, queue operation and result review.
- [Export metadata](EXPORT_METADATA.md): preserved metadata and limitations.
- [Lookout operating guide](LOOKOUT.md): daily UX and operational improvement reports.
- [Performance, reliability and operations](PERFORMANCE_RELIABILITY_OPERATIONS.md): baseline, limitations and improvement proposals.
- [Agreed decisions](DECISIONS.md): product preferences and adjustable defaults.

## Product plans and historical reference

[Project design](PROJECT_DESIGN.md) and [original implementation plan](PROJECT_PLAN.md) describe the broader planner/trial/production product vision. They are not a completion checklist for today's implementation. [Lookout plan](LOOKOUT_PLAN.md) preserves its original delivery plan; use the operating guide for current operation. [Prototype guide](PROTOTYPE.md) preserves earlier commands and algorithms, including legacy modes and historical experiments.

When older descriptions differ, the current implementation guides above take precedence. Saved runs retain their original settings and evidence; documentation or code changes do not upgrade existing analysis.

## Measured experiments

- [Adaptive verification replay (2026-09-29)](experiments/ADAPTIVE_VERIFICATION_2026-09-29.md): saved sailing evidence, call savings, missed rejection checks and limits of motion-only scheduling. Experimental findings, not production defaults.
