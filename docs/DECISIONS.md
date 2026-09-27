# Agreed behavior

- Target for the example: the other lime-green-sailed dinghy, including sail, hull and sailor, selected around 40 seconds.
- Offline analysis; use the local Qwen3-VL model frequently for identification, verification and recovery.
- Permit strong digital zoom and resulting blur. Do not discard poor segments: the user will select usable footage afterward.
- Smooth camera framing. Preserve as much of the visible target as possible, including during leveling.
- Permit the viewport to extend beyond source boundaries. Feather source edges into a blurred extension; the extension is decorative, not recovered scene content.
- Briefly hold the camera path when tracking is uncertain, then widen. Ask the VL model to reacquire. Flag frames for relabeling rather than silently changing identity.
- Automatic first pass, with a review interface and correction data retained separately from model predictions.
- After the first pass, use a later confident detection to track backward through each preceding uncertain interval once. Extend the confident interval only when new evidence passes the confidence threshold; preserve first-pass results and report recovery provenance.

# Prototype defaults (adjustable, not user-mandated)

- 16:9, 1280x720 preview; target approximately 55% of output height.
- Configurable Qwen analysis FPS, currently 10 (0.1-second samples); source-rate output with per-frame refinement.
- Directional temporal history for both forward and backward passes, bounded to the model context window with auditable summaries.
- Hold 0.75 seconds, widen over 2 seconds when target is missing.
- Optional gyro-final leveling for inspected DJI Action 6 files: decoded per-frame fused attitude supplies the applied rotation; independent Qwen visual estimates are retained for comparison. The image-axis mapping remains provisional and visible in diagnostics. Other camera adapters and full calibration remain future work.
- Highlight visual/gyro differences above a configurable threshold (initially 5 degrees). Qwen leveling receives only the current image and image-derived line candidates, without previous angles or telemetry values.
- A 2 FPS leveling test can reuse completed 2 FPS target tracking; record that provenance and keep the previous outputs.
