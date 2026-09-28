# Identity and localization verification

New analyses use verification schema 7. The approved project description is the identity used by independent detection, adjudication, retries, and verification. If no approved description exists, detection falls back to the original `target`; verification retains the blind reference-crop fallback. Neither field is rewritten by analysis.

Human-label crops and proposed crops use the same blind image-to-text prompt. It receives only the crop, never the intended identity, history, proposal note, or confidence. It reports `box_description`, `composition` (isolated_subject, multiple_subjects, scene_dominated, unclear), `visibility` (whole, boundary_cut, occluded, unclear), and `viewpoint` (external_view, surrounding_camera, unclear). These viewpoint categories describe evidence; no viewpoint is preferred universally. Spatial relationships help distinguish objects without hardcoding any sport, equipment, or preferred viewpoint.

The shared text comparison evaluates that observation against the approved description. It returns an identity match score, presence, explicit exclusion status and explanation, localization support and explanation, differences, and completeness. A supported exclusion contradiction must produce absence and a zero identity score. Missing evidence is distinct from a contradiction. Blur, low resolution, and partial visibility alone are not reasons to lower identity confidence.

## Acceptance

`verification_policy.py` is the shared decision policy:

- Identity: target present, finite score at least the configured acceptance threshold, no explicit exclusion contradiction.
- Crop: identity passes and localization support is `supported`.
- Independent box: crop passes, valid source-normalized coordinates, visible/partial target, no error, scene cut, or unresolved conflict.
- Optical propagation: accepted crop plus the existing reliable-flow and expansion limits. This validates the relaxed search crop; it does not independently localize the predicted rectangle.
- Automatic anchor: accepted independently localized box, score at least both acceptance and anchor thresholds, exclusions positively resolved, no unresolved conflict. Propagated-only boxes cannot become anchors.
- Human boxes remain authoritative; marked absence remains absence.

Completeness is diagnostic, not an acceptance gate for new analyses. Default thresholds remain 50% acceptance and 85% anchors. Exclusion `unclear` can allow ordinary tracking with otherwise supported evidence, but prevents automatic anchor promotion.

Composition is evidence supplied to comparison, not a hardcoded rule that all multi-object crops fail. Textual localization support cannot prove exact coordinate accuracy. A broad scene containing matching features is explicitly insufficient evidence of an isolated target.

Retries are bounded by the existing configurable 0–2 retries. Localization rejection asks for an isolated corrected box; identity rejection asks for another candidate satisfying the approved identity. Partial visibility alone does not trigger a retry. Rejected estimates remain available in path diagnostics and overlays, but cannot drive selection or rendering as accepted observations.

## Review and progress

Frame Analysis shows composition, visibility, localization support/reason, identity exclusion status/reason, and the recorded decision and threshold for each path. The identity score remains visible even when localization rejects the box.

Progress retains accepted/rejected/error totals and adds rejection categories: identity, localization, request error, and unclassified. Counts describe latest outcomes at unique positions, not an additive history of all attempts. Any accepted path makes a position accepted; otherwise localization evidence takes precedence over identity rejection when grouping mixed path outcomes. Medium/high counts for new runs require the same acceptance policy. Raw optical visits remain motion-quality measurements, not verified target detections.

## Versions and operation

Crop description v4, text comparison v4, verification v7, and detection v7 invalidate their relevant caches. Review-description evidence also includes schema versions. Changed detection/verifier versions invalidate anchor checkpoints. Existing saved runs retain historical results; rerendering does not reverify them. New analysis is required to obtain the new judgments.

Queue inputs are snapshots, including the approved description. Each queued job starts a fresh process and reads the then-current code. Updating source files does not provide atomic release isolation: pause queue advancement during a multi-file update, validate, then resume. The already-running job continues with its loaded code.

## Validation

Regression cases cover complete, partial, blurred/unclear, wrong-subject, scene-wide, absent, malformed, and request-error evidence; independent selection; human overrides; optical-only anchor exclusion; progress categories and resume; approved-description prompts; partial-target early stopping; and bounded retries. These tests verify policy behavior, not model accuracy. Live saved-crop checks are additional spot checks, not a calibrated evaluation of the whole video.

Live Qwen spot check on three saved project_f43da7a9 crops: the human reference crop passed at 90%; a broad scene dominated by foreground equipment was rejected for an explicit viewpoint contradiction; a water-only crop was rejected. Earlier prompt iterations incorrectly accepted the foreground scene, so the final prompt defines camera-relative viewpoint explicitly. The final comparison still returned a nonzero raw score together with a contradiction: code enforces rejection and zero effective identity confidence for explicit contradictions, retaining the raw score for audit. This normalization is shared with human-description checks. These three cases do not establish whole-video accuracy; review new results before drawing broader conclusions.
