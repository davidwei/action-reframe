# Offline zoom smoothing

Rendering now applies three operations across **every frame**, including adjacent framing anchors and raw/leveled path switches:

1. Smooth the desired camera scale in log space, so changes are proportional rather than fixed increments of magnification.
2. Enforce a maximum change in log zoom between adjacent frames.
3. Look ahead across the saved video so a future larger target box causes widening before that frame, while the forward pass prevents an abrupt zoom back in afterward.

Tracking selection and analysis are unchanged. Existing analysis can be rerendered.

## Settings

Video focus → Output exposes:

- **Seconds per 2× zoom change** (`zoom_seconds_per_doubling`): default **0.5 seconds**. Larger values mean slower transitions; must be positive.
- **Log-zoom smoothing (seconds)** (`zoom_smoothing_seconds`): default **0.15 seconds**, the Gaussian standard deviation in video time. Zero disables this preliminary smoothing, while preserving the speed bound and look-ahead.

The per-frame log bound is `log(2) / (fps × seconds_per_doubling)`. At 29.970 FPS with the default, neighboring magnifications differ by at most a factor of 1.04734. The same bound applies in either direction; a decrease expressed as a percentage of the prior zoom is slightly smaller than the reciprocal increase.

## Geometry and priorities

The existing interpolated zoom is the desired path, not the final path. The renderer smooths log crop height (equivalent to negative log zoom), enforces target-fit and minimum-crop bounds, and performs forward/backward maximum-envelope passes. This is linear-time work over the saved frames. It widens nearby frames enough to approach each size requirement within the speed bound.

The final path preserves the 180-source-pixel minimum crop short side, subject fit and margins. Rotation-aware edge coverage is a soft preference: it may be relaxed when the smooth path needs a wider viewport. There is no final edge-coverage clamp that can reintroduce a jump. Missing borders retain the existing feathered/blurred fill. Nominal 1× endpoints may be wider if nearby fit constraints require it.

Tracks record the smoothing settings and `zoom_edge_coverage_relaxed`. The corresponding review flag explains when the final crop exceeds the viewport size permitted by complete-edge coverage. `zoom_min` remains the edge-coverage recommendation; it is not a hard lower magnification bound in these frames. `zoom_max` reflects subject fit and the minimum crop size.

Camera-path cache version **4** includes both settings in its dependency key. A rerender recomputes the camera path but reuses compatible analysis records. New executions preserve resolved settings in their execution configuration records.

## Saved-run check

For run `6a31a214f7814257b9c20707ba64e801`, the selected raw/leveled boxes and gyro angles were reused without new model requests. All 1,902 computed frames satisfy the speed bound and minimum crop height.

| Frame | Old zoom | New zoom |
| --- | ---: | ---: |
| 1092 | 5.2206× | 3.9984× |
| 1093 | 5.1285× | 3.9834× |
| 1094 | 3.2571× | 3.8740× |
| 1095 | 3.2903× | 3.8585× |

The problematic single-frame decrease is approximately 2.75% after recomputing the camera path; widening begins earlier. This is a camera-path regression check. A newly encoded render is needed to inspect playback with the new path.
