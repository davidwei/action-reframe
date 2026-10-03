# Adaptive verification and minimum rendering crop

New projects default to **Adaptive**, as explicitly requested on 2026-09-29. **Evaluate only** remains available in Object tracking → Output → Verification scheduling and keeps actual verification while recording proposed decisions. **Fixed cadence** disables skipping. Running processes retain their loaded policy. Existing queued snapshots retain explicit settings unless deliberately migrated; the waiting analyses were migrated to Adaptive at the user’s request with their previous inputs archived.

## Output settings

- **Minimum crop short side:** 180 source-image pixels by default.
- **Tiny-box ratio:** 50%, producing a 90-pixel threshold. A box is tiny if either dimension is strictly below that threshold; there is no area threshold.
- **Verification scheduling:** Fixed cadence, Evaluate only, or Adaptive.

The output preserves the source aspect ratio by default (`preserve_source_aspect: true`), using the configured output dimensions' longer side as its resolution budget. Encoded dimensions are rounded to even pixels. For a 180-pixel minimum shorter side, minimum source crops are 320×180 at 16:9, 180×320 at 9:16, 240×180 at 4:3 and 180×180 at 1:1. Source aspect preservation can be disabled explicitly in configuration when a different output aspect is wanted.

Tracking boxes remain unchanged. Rendering interpolates zoom and enforces the hard minimum crop dimensions throughout the camera path. If edge coverage would require a tighter crop than this minimum, the minimum wins and missing borders use feathered background fill. A conflict remains flagged. Rerendering applies the limit without rerunning analysis; saved analysis decisions keep their original thresholds.

## Analysis behavior

Each branch has its own video-time state, serialized into its candidate records and therefore retained in scheduler checkpoints. Forward and backward traversals use absolute source-time distance. Human labels reset the identity timer; absence remains authoritative.

For reliable optical motion:

| Condition | Adaptive action |
| --- | --- |
| Either analysis-view box dimension below the tiny threshold | Skip crop-only verification, retain unverified motion for framing; attempt independent recovery on the discovery grid |
| Motion strong and last passed crop isolated with supported localization | Verify after 0.5 seconds |
| Motion intermediate, last crop well localized | Verify after 0.25 seconds |
| Weak motion, abrupt geometry change or uncertain prior localization | Verify at the next checkpoint allowed by Crop Verification FPS |
| Motion fails | Recover independently on the discovery grid |

No verification attempt runs more frequently than `1 / analysis_fps`; skipped checks do not refresh identity or become anchors. An intentionally deferred, recently verified non-tiny optical result may cover a discovery position for scheduling purposes, without being presented as newly identity-verified. Tiny crops never receive that coverage exemption.

Independent recovery remains capped at the configured discovery rate (default 2 FPS). For a tiny independently detected box in adaptive mode, its identity verification uses an expanded context region with a minimum 180-pixel width and height, clipped to the analysis image; it does not repeat crop-only verification on the tiny region. The original detection coordinates are retained, and `verification_region` records the different evidence region. The ordinary identity/localization acceptance policy still applies; context does not guarantee an accepted detection.

Strong motion requires quality ≥0.70, ≥12 features, retention estimate ≥0.50 and flow residual ≤0.75 px. Weak motion means quality <0.50, <8 features, retention estimate <0.30 or residual >1 px. The retention estimate is the product of per-step surviving-feature fractions since the last successful check; it survives checkpoint reinitialization but is not a count of persistent feature identities. Over approximately 0.1 seconds, scale outside 0.90–1.10 or center movement over 0.25 box diagonals requests a check. Geometry warnings persist until a verification opportunity. These thresholds remain experimental.

Stable and intermediate intervals can be configured through `adaptive_verification.stable_seconds` and `intermediate_seconds`. Timing persists across optical checkpoint reinitialization. Evaluation mode updates its simulated schedule only on checks that policy would select; actual checks and production branch decisions continue normally, so it is not a full counterfactual trajectory simulation.

## Inspection and compatibility

Frame Analysis in both review views shows actual/proposed verification, reason, mode, box pixel dimensions, tiny threshold/status, last passed identity frame/age, and render crop dimensions/minimum. Raw and leveled branch results remain separate. Measurements use the unit-scale analysis view, not an enlarged presentation image or the rotation-inflated raw enclosing rectangle.

New optical records expose flow error and scale (stage version 3). Camera-path records use version 4 and include the minimum crop size and [zoom smoothing settings](ZOOM_SMOOTHING.md) in their dependency key. Anchor checkpoint version 5 prevents incompatible old schedules from resuming with new state semantics. Heavy model evidence remains reusable when its exact dependencies match.

## Validation

Regression tests cover threshold boundaries, invalid settings, forward/backward timing, state persistence, ambiguous/rejected evidence, tiny-box skipping versus evaluation-mode checks, portrait/square crops and rotation conflicts. A six-frame saved sailing interval after human frame 1004 produced twelve retained optical proposals across the two branches with zero Qwen calls in adaptive mode; its camera path respected the minimum crop height. This is a smoke check, not a full-video quality benchmark. Inspect drift/recovery in new adaptive analyses; the smoke check does not establish whole-video accuracy.

The earlier [saved-evidence replay](experiments/ADAPTIVE_VERIFICATION_2026-09-29.md) used the earlier tiny-target assumptions and informs the localization gate; it does not establish the accuracy of the new 90-pixel tiny-target policy.
