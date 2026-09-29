# Independent raw and leveled tracking

New dual/anchor analyses use two separate optical states. Legacy completed outputs remain readable. The explicit single-path mode retains its older implementation.

| Branch | Motion proposal | Recovery proposal |
| --- | --- | --- |
| Raw | Optical flow between source frames | Independent Qwen localization in the raw image |
| Leveled | Optical flow between gyro-leveled frames | Independent Qwen localization in the leveled image |

Analysis never applies rendering zoom. Both branches store raw-space normalized boxes and source polygons, plus the analysis transform. The leveled view uses a fixed padded canvas at unit scale. For each step, the preceding winning box center is the pivot for both images; each image uses its own gyro roll. Before changing pivots, the tracker rebases its existing feature points and corners and reconstructs the previous grayscale image in the new coordinates.

**If no usable previous box exists, independent recovery rotates around the raw image center. It does not reuse a stale historical box center.** Once recovery succeeds, that box becomes the next optical seed. The expanded canvas can cost more CPU/memory than raw tracking; it avoids rendering zoom or perspective changes in analysis.

Optical flow visits consecutive source frames. Crop verification runs at analysis checkpoints (configured analysis FPS, plus scheduler/reference positions). Intermediate predictions explicitly carry `confidence_measurement: inherited` and the source `confidence_frame`; these are not new Qwen confidence measurements. Optical quality and crop identity remain separate quantities.

Independent recovery is restricted to a fixed discovery grid capped at 2 FPS per path, when motion is unavailable or identity verification fails. One localization per path/grid point is retained during a search instance; structured-output error retries remain possible. Verification-driven localization retries are disabled in this engine. Unscanned intervals are discovered after propagation. Accepted independent detections may seed both directions below the high-anchor threshold; high-confidence localized detections still become priority anchors.

Every frame's available proposals are appended to `path_candidates.jsonl` under `raw_angle_detection`, `raw_angle_optical`, `leveled_detection`, and `leveled_optical`. Not all four need to exist. Each branch picks its highest crop-confidence eligible seed. The final render picks the highest crop-confidence eligible candidate across both branches, retaining the prior choice on equal scores. A usable candidate is either policy-accepted evidence or reliable optical motion (including an identity-unverified fallback). Human labels and absence override automatic choices. Motion quality is never substituted for identity confidence. Failed discovery cannot erase successful optical evidence; agreeing candidates do not gain artificial confidence.

Rendering performs camera smoothing, rotation-aware zoom constraints, and compositing. Rerender jobs copy the four-candidate file and reuse the analysis without Qwen. Frame Analysis lists the four saved candidates and whether each score was measured or inherited; cyan/orange show the highest-score available proposal for each branch, and magenta shows the strongest available optical prediction.

## Gyro setup and compatibility

Gyro is now the default leveling source. New dual/anchor analysis requires it and raises an actionable error if a project still explicitly selects visual leveling, or if the video lacks supported attitude telemetry. No silent zero-angle substitute is used. Existing snapshots are not rewritten. For an old source project, choose **Output → Leveling → Gyro**, save tracking settings, review/approve the changed project, and queue a new analysis. A currently running process continues with its already-loaded implementation.

## Verification

Tests cover independent branch seeds and frame records, confidence selection, preservation after failed discovery, medium-confidence propagation, unit-scale coordinate rebasing, the 2 FPS grid, image-center recovery even when historical boxes exist, and rendering/human-label precedence. A short real DJI interval (human frame 1148 through 1151) is used as an additional smoke check without changing the original project's outputs.

## Adaptive cadence and rendering floor

See [adaptive verification](ADAPTIVE_VERIFICATION.md) for the new evaluation/opt-in scheduling policy. In adaptive mode, crop checkpoints are opportunities rather than unconditional model calls. Tiny optical crops remain unverified, and independent recovery uses wider context. Rendering now enforces a configurable 180-pixel minimum short side; the limit wins over edge coverage if they conflict.

## Processing cadences

| Operation | Default cadence | What it means |
| --- | --- | --- |
| Optical motion | Source FPS, in either direction | Update raw and leveled feature tracks through adjacent frames |
| Crop verification | 10 FPS checkpoints | Describe the predicted crop and compare with approved identity text; scheduler/reference positions can add checkpoints |
| Independent discovery/recovery | At most 2 FPS per path on a fixed grid | Localize with Qwen when motion is unavailable or unverified, and scan unresolved regions |

The UI calls the second setting **Crop Verification FPS**; its configuration/CLI keys remain `analysis_fps` / `--analysis-fps`. These are scheduling cadences, not processing speed. Optical frames can be revisited, and independent recovery can invoke crop verification too.

## Per-frame decisions

1. Respect human boxes or explicit absence. Otherwise load each branch's usable preceding winner in the current traversal direction.
2. Run raw optical flow in source coordinates. Run leveled optical flow in rotation-only coordinates, rebasing around that branch's preceding winner as described above.
3. At a verification checkpoint, crop and independently describe the proposal, compare against the approved identity, and record a measured confidence. Between checkpoints record inherited confidence and its source frame.
4. On a discovery-grid position, independently recover any unavailable/unverified branch. Keep its detection and optical proposal separately; neither overwrites the other merely because it ran later.
5. Within each branch choose the highest crop-identity-confidence eligible candidate as the next seed. An accepted independent detection can replace the motion prediction; the other branch keeps its own state.
6. Later, rendering chooses the highest-confidence eligible candidate across all four, with prior-choice tie preference and authoritative human corrections. A rejected independent estimate is not automatically eligible merely because its numeric score is high. Reliable unverified optical motion remains eligible as an explicitly uncertain fallback.

| Stored candidate | Image used | May seed |
| --- | --- | --- |
| `raw_angle_detection` | Raw frame plus rotation/context | Raw optical branch |
| `raw_angle_optical` | Adjacent raw frames | Raw optical branch |
| `leveled_detection` | Gyro-rotated, unzoomed frame | Leveled optical branch |
| `leveled_optical` | Adjacent gyro-rotated, unzoomed frames | Leveled optical branch |

All proposals return to canonical raw coordinates. The output camera's zoom or chosen render box does not feed back into analysis. Paths are logically independent but the current worker executes their operations sequentially; this design does not imply simultaneous Qwen requests.

See [scheduler](ANCHOR_TRACKING.md) for video-wide traversal, [verification policy](VERIFICATION_POLICY.md) for eligibility, and [stage records](STAGE_RECORDS.md) for selective reuse. Implementations: [branch execution](../src/two_path_tracking.py), [candidate selection](../src/path_candidates.py), [rendering](../src/reframe.py).
