# Current approach

Build an offline tool that follows a user-selected subject in action footage, levels the camera, smoothly reframes, and lets the user review and select useful footage afterward. The subject can be a distant, blurred or partially visible object. Automatic analysis must remain inspectable and correctable.

## Agreed tradeoffs

- Strong digital zoom and blur are acceptable. Preserve uncertain footage for review rather than automatically discarding it.
- Prefer smooth framing over immediate camera reactions. Rendering interpolates zoom between framing boxes, with nominal 1× endpoints and rotation-aware constraints. These constraints can override the nominal endpoints.
- Preserve visible subject content where feasible. Extend missing borders with a feathered, blurred background. This is decorative fill, not reconstructed scene content.
- Reliable optical predictions may guide framing without passing identity verification. Keep motion quality, measured identity confidence and inherited confidence distinct.
- Human labels and explicit absence override automatic results. Flag uncertainty and model-output failures for review.
- Offline processing can use Qwen frequently. Keep heavy detection, crop description/comparison, optical motion and rendering evidence separately reusable.

## Architecture and implemented workflow

Four core components remain the foundation:

| Component | Current responsibility |
| --- | --- |
| Human labeling | Draw raw-space or transformed-view polygons; approve estimates; mark absence; edit, check, approve and restore description revisions |
| Verification | Blindly describe crops, then compare text with the approved identity; distinguish identity from localization |
| Independent detection | Locate a subject with Qwen and verify the crop, separately in raw and leveled views |
| Motion tracking | Propagate each branch with optical flow and periodically verify its predicted crop |

The **video scheduler** expands forward/backward from labels and accepted detections, then discovers unresolved regions. The **folder workflow** collects approved inputs and processes queued videos offline. Leveling, camera smoothing, compositing and review consume those results. See [video processing paths](TWO_PATH_TRACKING.md) for the per-frame rules and [architecture roadmap](ARCHITECTURE_ROADMAP.md) for remaining work.

The library supports New, Draft, Ready, Processing and Done projects; labels/descriptions open the relevant Video focus section. Analysis and rerender jobs share a persistent serial queue. Rerenders take priority over waiting analyses without interrupting a running job. Completed results remain available while a new attempt runs or fails. Jobs execute outside the browser/Codex session.

Queued inputs are snapshots. Each job starts a fresh process using the installed code at that time; changing a source project does not rewrite queued inputs. Review/approve and queue fresh inputs when settings change. Running jobs keep their loaded implementation.

## Defaults and review

New projects inherit shared defaults: gyro leveling; independent raw/leveled optical branches; 10 FPS **Crop Verification FPS** (`analysis_fps` internally); discovery capped at 2 FPS per branch; source-FPS optical flow; 50% acceptance; 85% priority anchors. Existing projects retain their settings.

Video focus and synchronized comparison expose exact-frame evidence, confidence provenance and configuration differences. Estimated cyan/raw, orange/leveled, magenta/optical and green/selected outlines are dotted; human labels are solid white. An available estimate can be approved even at zero confidence. Unsampled frames do not borrow nearby independent detections as their own evidence.

Description changes are explicit user actions. Positive crop checks should reach 80%; marked-absent examples should stay at or below 20%. Draft/check requests persist their status across navigation and prevent duplicate work for the same project; different projects may run concurrently. These requests run in the review server, so a server restart interrupts them.

## Adaptive verification and crop limits

New projects default to Adaptive at the user’s request. Evaluation-only mode remains available for comparisons. Adaptive mode skips tiny optical crops below half the minimum rendering short side (90 px by default) and spaces checks on reliable, well-localized motion. Rendering enforces a 180-source-pixel minimum short side and preserves the source aspect ratio; this hard zoom limit takes priority over edge coverage when they conflict. See [implementation and validation](ADAPTIVE_VERIFICATION.md).

## Current limitations

New two-path analysis requires supported gyro telemetry. The inspected DJI attitude adapter is not a general adapter for all cameras; its axis mapping remains provisional. Gyro-free skiing or ocean footage needs a validated visual-leveling path/adaptor before the same workflow can be promised. Qwen visual roll is an independent comparison, not an override of gyro rotation.

Optical tracking and rendering are CPU-based. Confidence is a model heuristic, not a calibrated probability; crop text cannot prove exact box geometry. Scene changes, tiny targets and occlusion still need review. Live label updates are not guaranteed to affect an already-running analysis. Full planner generation/review, separate trial approval, useful-segment export and image enhancement remain product work.

See [stage records](STAGE_RECORDS.md) for cache boundaries, [folder workflow](BATCH_WORKFLOW.md) for operating details and [documentation guide](README.md) for plans versus current guides.
