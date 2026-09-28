# Identity and localization verification

New analyses use verification schema 7. The approved project description is the identity used by independent detection, adjudication, retries, and verification. If no approved description exists, detection falls back to the original `target`; verification retains the blind reference-crop fallback. Neither field is rewritten by analysis.

Human-label crops and proposed crops use the same blind image-to-text prompt. It receives only the crop, never the intended identity, history, proposal note, or confidence. It reports `box_description`, `composition` (isolated_subject, multiple_subjects, scene_dominated, unclear), `visibility` (whole, boundary_cut, occluded, unclear), and `viewpoint` (external_view, surrounding_camera, unclear). These viewpoint categories describe evidence; no viewpoint is preferred universally. Spatial relationships help distinguish objects without hardcoding any sport, equipment, or preferred viewpoint.

The shared text comparison evaluates that observation against the approved description. It returns an identity match score, presence, explicit exclusion status and explanation, localization support and explanation, differences, and completeness. A supported exclusion contradiction must produce absence and a zero identity score. Missing evidence is distinct from a contradiction. Blur, low resolution, and partial visibility alone are not reasons to lower identity confidence.

## Acceptance

`verification_policy.py` is the shared decision policy:

- Identity: target present, finite score at least the configured acceptance threshold, no explicit exclusion contradiction.
- Independent crop: identity passes and localization support is `supported`.
- Optical crop: identity passes and localization is `supported` or `ambiguous`, provided motion is reliable. `unsupported` localization and explicit identity contradictions still fail verification. Confidence thresholds are unchanged.
- Independent box: crop passes, valid source-normalized coordinates, visible/partial target, no error, scene cut, or unresolved conflict.
- Optical propagation: accepted crop plus the existing reliable-flow and expansion limits. This validates the relaxed search crop; it does not independently localize the predicted rectangle.
- Automatic anchor: accepted independently localized box, score at least both acceptance and anchor thresholds, exclusions positively resolved, no unresolved conflict. Propagated-only boxes cannot become anchors.
- Human boxes remain authoritative; marked absence remains absence.

Completeness is diagnostic, not an acceptance gate for new analyses. Default thresholds remain 50% acceptance and 85% anchors. Exclusion `unclear` can allow ordinary tracking with otherwise supported evidence, but prevents automatic anchor promotion.

Composition is evidence supplied to comparison, not a hardcoded rule that all multi-object crops fail. Textual localization support cannot prove exact coordinate accuracy. A broad scene containing matching features is explicitly insufficient evidence of an isolated target.

Retries are bounded by the existing configurable 0–2 retries. Localization rejection asks for an isolated corrected box; identity rejection asks for another candidate satisfying the approved identity. Partial visibility alone does not trigger a retry. Rejected independent detections remain diagnostic estimates. Reliable optical predictions can drive framing without being treated as verified identity, as described below.

## Review and progress

Frame Analysis shows composition, visibility, localization support/reason, identity exclusion status/reason, and the recorded decision and threshold for each path. The identity score remains visible even when localization rejects the box.

Progress retains accepted/rejected/error totals and adds rejection categories: identity, localization, request error, and unclassified. Counts describe latest outcomes at unique positions, not an additive history of all attempts. Any accepted path makes a position accepted; otherwise localization evidence takes precedence over identity rejection when grouping mixed path outcomes. Medium/high counts for new runs require the same acceptance policy. Raw optical visits remain motion-quality measurements, not verified target detections.

## Versions and operation

Crop description v4, text comparison v4, verification v7, and detection v7 invalidate their relevant caches. Review-description evidence also includes schema versions. Changed detection/verifier versions invalidate anchor checkpoints. Existing saved runs retain historical results; rerendering does not reverify them. New analysis is required to obtain the new judgments.

Queue inputs are snapshots, including the approved description. Each queued job starts a fresh process and reads the then-current code. Updating source files does not provide atomic release isolation: pause queue advancement during a multi-file update, validate, then resume. The already-running job continues with its loaded code.

## Validation

Regression cases cover complete, partial, blurred/unclear, wrong-subject, scene-wide, absent, malformed, and request-error evidence; independent selection; human overrides; optical-only anchor exclusion; progress categories and resume; approved-description prompts; partial-target early stopping; and bounded retries. These tests verify policy behavior, not model accuracy. Live saved-crop checks are additional spot checks, not a calibrated evaluation of the whole video.

Live Qwen spot check on three saved project_f43da7a9 crops: the human reference crop passed at 90%; a broad scene dominated by foreground equipment was rejected for an explicit viewpoint contradiction; a water-only crop was rejected. Earlier prompt iterations incorrectly accepted the foreground scene, so the final prompt defines camera-relative viewpoint explicitly. The final comparison still returned a nonzero raw score together with a contradiction: code enforces rejection and zero effective identity confidence for explicit contradictions, retaining the raw score for audit. This normalization is shared with human-description checks. These three cases do not establish whole-video accuracy; review new results before drawing broader conclusions.

## Frame-local runtime failures in dual mode

Detection v8 requests JSON-object output and validates the returned rectangle, confidence, and visibility. Absence must use `bbox: null`, never `[null]`. Malformed JSON/schema or an empty response gets one corrective generation retry, separate from the existing bounded crop-verification retries. Truncation also receives one retry with an increased output allowance. Raw response envelopes and structured errors are saved for diagnosis. Detection notes are requested as short sentences.

Dual forward and backward passes now record model-output failures in `analysis_failures.json`, the existing frame review queue, instead of aborting after three consecutive bad pairs. A valid alternative path remains usable. Failed detection/crop responses are excluded from subsequent history; backward traversal skips malformed-output gaps using its last successful seed. A valid low-confidence or absent backward result still ends that propagation chain. Connection, timeout, HTTP/service and other system failures remain fatal rather than being silently converted into lost targets.

Regression tests replay the malformed absence shapes seen at frames 869, 899 and 929, verify corrective retries and retained response audits, continue across three consecutive failing pairs, preserve the good alternative path, skip failed history, preserve backward seeds, and confirm service outages still stop processing. A schema-version change starts a fresh detection cache; retrying old saved inputs uses the new code but does not reuse older detection-version results. Existing successful renders remain available in the folder view.

## Optical prediction overlay

Video focus offers a default-on “Show optical predictions (purple)” toggle. Purple dotted rectangles show source-space optical predictions before identity/crop acceptance, on both raw and transformed views. Frame Analysis labels motion quality separately from identity confidence. Failed motion estimates never draw the held previous box as a prediction.

New anchor processing appends each visited frame's motion result to `optical_motion.jsonl` before validation. The latest attempt per frame is displayed; attempts remain in the log. A fresh analysis resets that diagnostic log, while checkpoint resume retains it and rerender snapshots copy it. The UI server caches decoded logs until their size/mtime changes. Existing runs can expose checkpoint predictions retained in `propagation_validation`; unavailable intermediate predictions are not interpolated or invented.


## Per-frame optical framing independent of verification

Reliable optical predictions are retained at every visited source frame and used for camera centering and zoom even if identity/crop verification fails. Existing center smoothing, gap interpolation and 1x endpoint zoom remain in place. Human boxes and explicit absence corrections take precedence; accepted independent observations take precedence over unverified motion. Failed motion never supplies a held box as a fresh prediction. Historical checkpoint predictions can also be used on rerender, but missing intermediate frames are not invented.

A motion branch may continue after failed verification/local detection while optical motion remains reliable. Such rows are labeled `optical_unverified`, carry no verified identity confidence, cannot become anchors, and do not suppress independent discovery. Explicit manual absence terminates that branch. Motion failures still trigger independent recovery. Per-frame motion remains usable for framing even when independent discovery later fails at the same sample.

Verification policy v2 relaxes only ambiguous localization for reliable optical propagation. The existing per-project confidence threshold is unchanged; explicit contradictions, absent targets, insufficient confidence and unsupported localization remain unverified. Automatic anchors still require independently supported localization, the high threshold and resolved exclusions. Identity score and motion quality remain separate. Unverified optical framing appears in render review flags and source provenance; the purple overlay remains a motion prediction, not evidence of verified identity. Rerendering uses saved motion without model calls; new analysis is required to obtain additional per-frame predictions or new verification judgments.

A live smoke check on frames 1148–1151, starting from a saved human label, retained all three per-frame optical predictions and accepted the checkpoint crop at 80% identity confidence. Regression tests additionally verify unverified-branch continuation, unchanged confidence thresholds, manual-absence precedence, anchor exclusion, and actual video rendering driven by an unverified motion box.
