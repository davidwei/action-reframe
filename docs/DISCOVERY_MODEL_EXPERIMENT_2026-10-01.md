# Local object discovery and verification experiment — 2026-10-01

Status: complete. All four candidates finished both relevant evaluation sets.
The original production Qwen3-VL-32B-FP8 service is restored, its exact served model
identity is verified, and a live inference smoke test returned `READY`.

## Scope

Compare the same candidates used in the leveling experiment:
Qwen3-VL-32B-FP8 (control), Qwen3.8-27B-FP8, Qwen3.6-35B-A3B-FP8,
and Gemma-4-31B-it with online FP8 quantization. All use the same isolated vLLM
0.30.0 runtime and two RTX 5090 GPUs. The production environment remains unchanged.
Weights and revisions are recorded in the leveling experiment report and runtime plan.

There are three independently measured responsibilities:

1. Discover the selected object in a full frame, using an identity reference crop.
2. Describe a supplied crop without seeing the intended identity, then verify it.
3. Compare a fixed crop description against the approved identity using text alone.

## Dataset and protocol

Four existing sailing projects: two green-sail normal-speed clips and two white-sail
slow-motion clips. Each contributes three held-out positive frames and two human-marked
absent frames. The single identity reference for each clip is a different human-labeled
frame, separated from test frames by more than 15 frames. Test boxes are not supplied
to discovery. This tests independent discovery, not optical tracking or temporal history.

- 20 raw-frame discovery cases; 10 additional gyro-leveled cases from the green-sail clips.
- 20 blind image descriptions: 12 human target crops and eight absent full frames.
- 32 crop/identity decisions: those 20 plus 12 mismatched green/white target descriptions.
- Eight controlled text-only cases covering correct, blurry, partial, occluded,
  wrong-color, camera-relative, background-only, and unrelated-category observations.
- A second pass compares the same 32 real crop-description/identity pairs for every
  model, freezing descriptions from the control. Control measurements are reused,
  since their prompts and inputs are identical; they are not independent repeated trials.

Production prompts and validators are reused. Detection has a 650-token output budget;
observation and text comparison use 1000 tokens. A truncated response retries once with
an increased budget, as in production. Malformed discovery JSON is counted as an error
without the production contextual wrapper's optional format-repair retry. Temperature
is zero; thinking is requested disabled. Image requests have a 1280-pixel maximum full-frame
size; crop observation follows production's 960-pixel maximum. All calls are serial.
No production analysis cache or project labels are modified.

## Interpretation

Discovery success requires overlap with the human box, not merely a non-null answer.
Localization evaluates returned proposals before crop verification or confidence gating.
All observed absent-frame false positives also had self-reported confidence above 0.5.
Report IoU at 0.5 and 0.25, mean IoU, false positives on absent frames, and schema failures.
Leveled predictions are mapped back to raw coordinates before comparing axis-aligned
bounding boxes; this metric does not fully measure polygon fit or visible-object coverage.

Identity decisions use target_present, match_score >= 0.5, and no explicit exclusion
contradiction. These are distinct from the additional localization gate used to promote
production tracking. Report false positives and false negatives separately. End-to-end
crop latency includes both blind observation and text comparison; comparison-only latency
is shown separately. End-to-end timing uses the 20 original crops; the 12 cross-target
negative comparisons reuse their image descriptions and contribute to accuracy, but
do not trigger a second image-description call. Retries count toward latency and
errors count against accuracy.

Human boxes are the practical reference, not pixel-perfect segmentation. Description
fidelity needs visual review: correct downstream classification does not mean every
word, marking, or object detail is correct. This small sailing-specific dataset cannot
establish general vision superiority or predict skiing performance. Reference/query
images come from the same clips, so this is not a cross-video generalization study.

## Reproduction and artifacts

Harness: [experiments/discovery](../experiments/discovery/README.md).
Machine-local artifacts are outside Git under `outputs/experiments/discovery-models`:
`dataset/manifest.json`, `runs/*/results`, `runs/index.html`, `shared_runs`, and the
model-swap plans. Each request preserves prompts, raw responses, token usage, retries,
wall latency, and image evidence. HTML reports show human and detected boxes.

Model swapping uses the runner's finally restoration plus an independent systemd
ExecStopPost guard. Completion requires restoring the original production model and
checking both its served identity and a live inference response.

## Measured first-pass results

All times below are medians in seconds, including retries when present. Discovery
latency covers both raw and leveled calls. Raw accuracy uses the same 12 positive
frames and eight absent frames for every model. “IoU ≥ 0.5” is localization recall
on positive human boxes. Crop accuracy includes both image description and comparison.

| Model | Raw boxes IoU ≥ 0.5 | Raw absent false positives | Discovery time | Correct crop decisions | Crop + comparison time |
|---|---:|---:|---:|---:|---:|
| Qwen3-VL-32B control | 6/12 | 1/8 | 3.27 | 30/32 | 6.18 |
| Qwen3.8-27B | 8/12 | 2/8 | 3.25 | 31/32 | 7.31 |
| Qwen3.6-35B-A3B | 3/12 | 1/8 | 4.19 | 28/32 | 7.63 |
| Gemma-4-31B | 5/12 | 0/8 | 1.92 | 32/32 | 4.62 |

| Model | Blind description time | Own-description comparison time | Crop false positives / false negatives | Median description words |
|---|---:|---:|---:|---:|
| Qwen3-VL-32B control | 3.41 | 2.79 | 2 / 0 | 100 |
| Qwen3.8-27B | 3.81 | 3.42 | 0 / 1 | 70 |
| Qwen3.6-35B-A3B | 3.40 | 4.12 | 3 / 1 | 52 |
| Gemma-4-31B | 2.00 | 1.99 | 0 / 0 | 46 |

All four models passed the eight controlled text-only cases. These easy cases alone
do not discriminate their ability to compare real, longer descriptions. The baseline
had one malformed discovery response (`bbox: [null]`); the other candidates had none.
There were no output truncations in this pass.

On the six positive gyro-leveled frames, IoU ≥ 0.5 counts were control 2/6,
Qwen3.8 4/6, Qwen3.6 2/6, and Gemma 1/6. At IoU ≥ 0.25 they were 5/6, 6/6,
6/6, and 6/6. Do not compare these denominators to the 12-frame raw results as
though they contained the same clips; slow-motion clips have no usable gyro.

## Visual and response audit

- `green_long`, frame 2988: the control's raw discovery box landed on water below
  the boat; Qwen3.8's box covered the intended boat. This is a coordinate/localization
  failure even though the control's text discusses the expected sailboat.
- `green_long`, frame 1723: both the control and Qwen3.8 proposed the foreground
  camera-boat sail during discovery, but their crop-verification decisions correctly
  rejected the camera-relative view. Discovery and verification should stay separate.
- `green_long`, frame 1478: Qwen3.6's blind description invented a wheeled platform /
  land yacht, and comparison then rejected the actual sailing target. This failure
  originated in image-to-text observation.
- `green_long`, frame 0: Qwen3.6's description correctly reported `surrounding_camera`,
  but its own comparison reason claimed an external viewpoint and accepted the crop.
  This failure originated in text comparison, not image observation.
- `white_short`, frame 61191: Qwen3.8 described a dark hull and rejected the intended
  white-sail boat because the approved description says white hull. The crop is blurry
  and shadowed; this demonstrates the cost of treating an appearance discrepancy as
  a decisive identity contradiction.
- The control accepted two white-sail descriptions against a lime-green identity at
  0.7 confidence. One reason explicitly noticed the sail-color mismatch but still
  accepted; another claimed white matched lime-green. Qwen3.6 also accepted two
  white-sail wrong-identity pairs at 0.8. Self-reported confidence is not evidence of accuracy.
- All models sometimes inferred specific sail lettering or equipment details unsupported
  by blurred imagery. Gemma was generally concise; even its correct 32/32 identity
  decisions do not establish that every word in its descriptions is visually correct.

The declared viewpoint matched the visually checked external/first-person arrangement
on 20/20 crops for the control, Qwen3.8, and Gemma, and 19/20 for Qwen3.6. This is one
narrow observation field, not a general description-accuracy score. Qwen3.6's mismatch
was the mostly-water frame `green_short_1822`, whose own boat bow is in the foreground.

## Identical real descriptions: text-only results

All models receive the same 32 description/approved-identity pairs. Request audits
confirm identical messages and token budgets. The control measurements are reused
from its original pass; other candidates run a separate text-only pass.

| Model | Correct | False positives | False negatives | Median seconds |
|---|---:|---:|---:|---:|
| Qwen3-VL-32B control | 30/32 | 2 | 0 | 2.79 |
| Qwen3.8-27B | 32/32 | 0 | 0 | 3.49 |
| Qwen3.6-35B-A3B | 29/32 | 3 | 0 | 4.28 |
| Gemma-4-31B | 32/32 | 0 | 0 | 2.52 |

## Conclusions and next experiment

- **Qwen3.8 is the strongest discovery-box candidate in this test**, with 8/12 raw
  boxes at IoU ≥ 0.5 and 4/6 leveled boxes, at approximately the control's discovery
  latency. Its raw absent false positives increased from 1/8 to 2/8, so keep verification.
- **Gemma is the strongest verification candidate here**: 32/32 end-to-end decisions,
  approximately 25% lower median end-to-end latency than the control, and 32/32 on the
  fixed real descriptions. Text-only comparison is about 10% faster than the control
  on those identical inputs. Its discovery boxes do not improve on the control.
- Qwen3.6 offers no compelling tradeoff in this test: weaker precise localization,
  slower comparisons, and false acceptances on contradictory identity descriptions.
- Do not infer that the best per-stage models form a validated hybrid. That combination
  has not been run end-to-end, and serving/switching costs must be measured on this
  machine. The present recommendation is to trial Qwen3.8 for discovery and Gemma for
  verification as separate choices, not silently change production.
- Before adopting either, enlarge the held-out set with real optical-tracker failures,
  expanded/background-heavy boxes, similar neighboring boats, and skiing footage.
  Repeat timing measurements under production concurrency and the selected runtime.
  The current results measure compatibility with existing prompts, not each model's
  best performance after model-specific prompt tuning.

Neither fine-text transcription nor full description fidelity is scored exhaustively;
visual audits identify obvious errors, while crop-verification accuracy measures the
practical identity decision. All controlled text cases passing does not imply perfect
reasoning: longer real descriptions exposed errors in the control and Qwen3.6.


## Validation and access

The two model-swap restoration tests and the rotation-coordinate round-trip test pass.
All 96 new shared-text request payloads match the control messages and token budgets.
The model-swap records confirm production restoration after both passes. The original
production model identity and a successful `READY` completion are saved as
`production-restored-models.json` and `production-restored-smoke.json` in the artifact root.

Open the experiment through the existing review server:
[interactive evidence index](http://127.0.0.1:8766/files/outputs/experiments/discovery-models/index.html).
This is a static experiment report, not a new server or production UI change.
The code, methodology, and measured summary are checked in; weights, source videos,
and bulky per-request evidence stay in the local experiment output directory.
