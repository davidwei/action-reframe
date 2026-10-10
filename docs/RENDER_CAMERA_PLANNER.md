# Visibility-first offline rendering

Rendering reuses selected analysis polygons and human corrections without Qwen. Manual absence excludes subject constraints. Missing polygons fall back to the saved framing boxes, including optical-only predictions; unverified geometry gets an extra 5 percentage points of margin, capped at 30%.

The renderer extracts DJI fused attitude (not raw gyro) through the existing timestamp-checked parser. Background features are measured after per-frame roll leveling, with target masks and border masks. RANSAC and forward/backward consistency gate the motion estimate. Only residual image-plane translation is applied. We do not assume calibrated intrinsics, or apply raw pitch/yaw rotations directly to DJI-stabilized pixels. An empirical quaternion-delta-to-image-translation fit uses alternating training/held-out samples. Only >=70% explained held-out motion permits a 20% telemetry contribution on visually supported frames; otherwise the fit is diagnostic only. Unsupported motion falls back to zero residual compensation, not invented telemetry. Histogram cuts reset the trajectory.

Polygons are placed in residual-stabilized coordinates, where the camera center is smoothed. Short gaps interpolate supported trajectories; long gaps widen and return toward source center. Exact absent labels suppress subject constraints. Zoom and center are coupled through polygon containment and crop-relative motion constraints. Tracked positions use nominal 1.5× object-relative framing, widened when visibility, motion, or the minimum crop requires it. A local look-ahead maximum envelope is applied only across the tracked interval. Untracked prefixes and suffixes use separate eased log-zoom transitions so their wider endpoints cannot flatten nearby tracked framing. Their endpoint width follows available duration and the configured speed/acceleration limits; it is capped by source height rather than forced to 1×. Only supported analysis polygons are used, clipped to source-image content. This is a conservative feasible planner, not a globally optimal constrained solver: it can choose wider framing than necessary, especially around isolated outliers. Original-edge coverage is soft; feathered fill is allowed.

Default `render_planner` settings: enabled, center_seconds 0.5, zoom_seconds 0.7, seconds_per_doubling 1.5, zoom_acceleration 0.45 log units/s², center_speed 0.6 crop units/s, center_acceleration 1.2 crop units/s², gap_seconds 1, motion_width 640, tracked_boundary_scale 1.5. Render into the final image once; background motion changes the planned center, not a prewarped source. Scene cuts are exempt from inter-shot transition limits. Camera-motion stage and camera-path stage cache independently; changing only framing settings currently conservatively invalidates the motion cache too.

`camera_motion.json` records per-frame background reliability and the held-out IMU fit. `camera_path_review.json` and `tracks.json` record polygon retained fraction, target offset, zoom velocity/acceleration and crop-relative camera speed/acceleration. Invalid or visibility-violating paths fail before encoding. The review UI shows these metrics. Old render outputs remain separate; rerender jobs preserve source analysis.

Limitations: background motion is a global translation approximation after leveling, not full 3D reconstruction; water/parallax/foreground rigging can confound estimates despite gating. Timestamp alignment uses the video's established constant-FPS assumption. Zoom-speed and acceleration bounds are explicit; jerk is reduced by smoothing but not hard-bounded. The sampled feature quality is an engineering reliability check, not proof of correct camera motion.


### Camera-plan cache version

The current planner uses camera-path stage version **7**, separately from the
background-motion evidence version. Version 5 can contain an earlier shot-wide
zoom-compression result, even when a run reports newer code. Rerendering now
recomputes the camera plan once, reusing compatible tracking and background-motion
records. Subsequent identical rerenders reuse version 7. Bump
`CAMERA_PATH_VERSION` in `render_planner.py` whenever camera-plan behavior changes;
do not bump the motion version for a centering/zoom-only change. The disabled
planner's legacy camera-path version remains separate.
