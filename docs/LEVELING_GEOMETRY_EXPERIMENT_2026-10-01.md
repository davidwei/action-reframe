# Qwen3.8 versus Gemma: leveling with direction derived from geometry

Status: complete. Both candidates completed 36 requests. Production Qwen3-VL-32B
was restored, its served identity verified, and live inference returned `READY`.

## Question

Can Gemma's speed advantage be retained while removing the inconsistent natural-language
direction field that caused most rejections in the previous leveling benchmark?

This changes only the experimental prompt/response adapter. Production leveling code
and model configuration remain unchanged. The model selects a candidate reference line
or supplies endpoints. Code computes the angle and direction from those endpoints, using
image dimensions and downward-positive image Y coordinates. Other geometry, candidate,
confidence, and cue validation stays in place; shoreline confidence remains capped.
The untouched model response is saved separately from the adapted response.

## Protocol

- Same isolated runtime, FP8 model variants, two RTX 5090s, 400-token output budget,
  temperature zero, and thinking-disabled request flag as the previous comparison.
- Original 12 frames: three slow-motion frames without gyro and nine with a provisional
  gyro reference. No gyro values or previous predictions are supplied to either model.
- Six added frames: expanded-canvas copies rotated by exactly -10° or +10° of the
  slow-motion 10-second frame and the original 44.51- and 55.02-second boat frames.
  Black padding preserves scene contents. Such padding is a synthetic-test artifact.
- Two serial passes per model: 36 requests each, including 24 original-frame requests.
- Original responses from the previous test are also rescored without the direction
  mismatch rejection, separating the effect of removing that gate from changing prompts.

Speed uses request latency for the original frames, excluding model loading. Report
mean and median; these are serial eager-runtime measurements, not saturated throughput.
Repeated frames can benefit from the server's prefix/image caches.

Accuracy is reported in distinct ways:

1. Valid estimates: schema/geometry/confidence checks pass. This is not correctness.
2. Absolute difference from the available gyro reference. That reference is not a
   calibrated ground truth for image horizon orientation, particularly with shoreline
   perspective or stabilization; it is a provisional comparison only.
3. Rotation consistency: rotating an image counterclockwise by +10° should reduce the
   measured downward-Y line angle by 10°. This tests equivariance, not absolute level.
   A consistently selected wrong line can pass this check.
4. Visual inspection of the selected reference lines and repeat consistency.

There is no independently measured absolute ground-truth angle for the three no-gyro
frames. This experiment cannot establish a general percentage accuracy for gyro-free
leveling or reliability on open ocean and skiing footage.

Harness: `experiments/leveling/geometry_benchmark.py`,
`geometry_compare.py`, and the existing guarded model-swap runner. Machine-local
artifacts live under `outputs/experiments/leveling-geometry`, outside Git.

## Results

| Measurement | Qwen3.8-27B FP8 | Gemma-4-31B online FP8 |
|---|---:|---:|
| Median seconds per original frame | 3.77 s | 1.78 s |
| Mean seconds per original frame | 3.79 s | 1.84 s |
| Mean absolute difference from gyro | 2.03° | 2.03° |
| Median absolute difference from gyro | 1.04° | 1.04° |
| Worst absolute difference from gyro | 8.06° | 8.06° |
| Maximum difference between repeats | 0.16° | 0.10° |
| Valid original-frame responses | 24/24 | 24/24 |
| Mean known-rotation consistency error | 0.83° | 1.39° |
| Worst known-rotation consistency error | 1.88° | 3.73° |
| Rotation tests within 2° of expected change | 12/12 | 10/12 |
| Request/schema failures | 0 | 0 |

The 24 original responses are 12 images repeated twice; the 12 rotation comparisons
are six transformed images repeated twice. They are not independent scene samples.
Gemma's median latency is **2.12× faster** (about 53% lower). Startup time is excluded.

Removing only the direction rejection from the *old saved responses* would have
changed Gemma's acceptance from 2/12 to 12/12, while Qwen3.8 stayed at 12/12. Thus the
previous acceptance gap largely measured direction-text inconsistency, not line-angle
accuracy. The fresh prompt removes that field entirely, and preserves original raw
responses alongside the geometry-adapted response.

## Accuracy findings from visual inspection

On the nine gyro-reference images, the models selected essentially the same measured
candidate lines, producing almost identical gyro differences. This is agreement under
a shared candidate generator, not independent proof of gravity accuracy. At 55.02s both
remain approximately 8.06° from the gyro reference. At 20s both selected a line on the
water below the actual land/water boundary. Removing direction rejection does not fix
these cue-selection or calibration problems.

The no-gyro frames distinguish the models more clearly:

- At slow-motion 0s, Qwen3.8's line follows the visible background boundary more closely.
  Gemma's line crosses above it on the right. Estimated angles are about 4.34° and 2.28°.
- At slow-motion 10s, Qwen3.8 selects a measured segment on the right-hand shoreline
  at 9.00°. Gemma supplies its own broad line at 4.06°, which does not follow that
  local shoreline as closely. Perspective means neither is established gravity truth.
- Qwen3.8 sometimes mislabels a land/water boundary as a true horizon, assigning more
  confidence than a shoreline warrants. Gemma consistently calls these shorelines.
- On the known rotations, Gemma's largest inconsistency occurs on that difficult
  10-second no-gyro frame. Qwen3.8 is more consistent, although either model can follow
  a consistently wrong reference and still pass a rotation test.

## Conclusion

**Gemma is now a viable, substantially faster leveling candidate with direction derived
in code.** Its previous 2/12 validation result should not be interpreted as 2/12 accurate
angles. For scenes with useful measured candidate lines, this test gives little reason
to pay Qwen3.8's extra latency based on gyro agreement alone.

**Qwen3.8 retains an advantage on difficult reference selection and rotation consistency
in this small set.** Since actual absolute angles are unknown on the no-gyro clips, do
not claim equal absolute accuracy or switch production solely from these results.
Further testing should use manually vetted distant references and gyro-calibrated
examples, including open ocean and skiing, and evaluate refusal when no level cue exists.
Production behavior was not changed by this experiment.

## Access and validation

[Visual report and metrics](http://127.0.0.1:8766/files/outputs/experiments/leveling-geometry/runs/index.html).
Each model report includes original and rotated input images, selected lines, repetitions,
angles, confidence, and latency. Raw responses and GPU telemetry remain in the artifact
folder. The runtime plan pins the same local model weights as the preceding comparison.

Three tests pass: rotation/direction geometry and both existing restoration safeguards.
Both model runs completed, the report URL returned successfully, and production restoration
was confirmed by `/models` plus a successful live `READY` completion. No production files
or project analysis settings were modified.
