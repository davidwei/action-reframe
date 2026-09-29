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
