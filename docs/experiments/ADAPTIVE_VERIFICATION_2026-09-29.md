# Adaptive verification: saved-evidence replay, 2026-09-29

The proposed motion-only scheduling rules are **not sufficient to adopt unchanged**. A candidate policy combining motion with the last crop's localization evidence is worth a controlled end-to-end trial. Production settings were not changed and no additional Qwen requests were made.

## Evidence and scope

A frozen snapshot of run `6a31a214f7814257b9c20707ba64e801` (`sailboat_verified_fps2`) contains 2,416 optical-update attempts and 808 measured optical-crop verification attempts, across raw/leveled branches and both traversal directions. Source frames range from 512 to 1417, approximately 17.08–47.28 seconds at 29.970 FPS. This is partial coverage from a still-running run, not a completed-video benchmark. Attempts include repeated visits; they are not unique frames.

The snapshot contains six rejected crop verifications. Every one has optical `motion_quality = 1.0`, 32–39 supporting features and reconstructed median forward/backward residual of approximately 0.0027–0.0069 pixels. All 808 measured attempts pass the proposed `q >= 0.70` and `n >= 12` strong-motion tests. These tests do not distinguish the observed bad crops.

Visual inspection of the six rejected crops shows mostly shoreline/dock/background with a narrow green sail region near the right boundary. Motion can remain consistent while the target is poorly framed. Nearby accepted crop descriptions also report multiple subjects and frequently ambiguous localization. The saved acceptance threshold is 25%, but even some 60–70% accepted scores accompany background-dominated crops; raising a score threshold alone is not established as a fix.

## Method

The replay joins optical stage-use entries to `optical_motion.jsonl` in original execution order, checking consistency against immutable optical stage records. Verification outcomes come from `path_candidates.jsonl`. It maintains separate state for branch, direction and source frame.

The per-step median residual can be reconstructed as `output_uncertainty - input_uncertainty - 0.15`; that is the current tracker's exact update formula, not a calibrated uncertainty model. Scale is reconstructed from the lengths of corresponding polygon edges. Center motion uses raw-space boxes. Over approximately 0.1 seconds, an abrupt-change trigger is scale outside 0.90–1.10 or center displacement exceeding 0.25 of the earlier box diagonal. Weak-motion triggers and strong/intermediate criteria follow the proposed table. Abrupt/weak triggers persist until the next available verification opportunity.

The replay uses existing measured checkpoints only, with minimum attempt spacing 0.1 seconds. Human seeds reset age. A successful selected check resets verification age; a skipped check cannot refresh it. The intermediate-motion interval is 0.25 seconds. The stable-motion interval varies below.

## Results

“Retained rejection checks” counts whether the policy selects the **same recorded checkpoints** that were rejected. It is not target-tracking recall or a ground-truth accuracy score.

| Policy | Selected / 808 checks | Checks skipped | Retained rejection checks |
| --- | ---: | ---: | ---: |
| Existing recorded checks | 808 | 0% | 6 / 6 |
| Motion rules, stable interval 1.0 s | 119 | 85.3% | 2 / 6 |
| Motion rules, stable interval 0.5 s | 195 | 75.9% | 2 / 6 |
| Motion rules, stable interval 0.25 s | 303 | 62.5% | 3 / 6 |
| Motion + crop-evidence gate, stable interval 1.0 s | 280 | 65.3% | 6 / 6 |
| Motion + crop-evidence gate, stable interval 0.5 s | 378 | 53.2% | 6 / 6 |

The **crop-evidence gate** permits slower verification only if the last selected check passed, its crop description says `composition == isolated_subject`, and its comparison says `localization_support == supported`. Otherwise check at the maximum configured cadence. Human labels initially qualify. Only checks actually selected by the replay update this gate; skipped historical results are not used to make decisions.

The stricter 0.25-second schedule does not necessarily retain more of every rejection episode: sampling phase matters, and later checks sometimes return acceptance for similarly background-dominated crops. Detection delay cannot be inferred solely from interval length.

For the 0.5-second gated candidate:

| Source-time bin (only recorded attempts included) | Available checks | Selected checks |
| --- | ---: | ---: |
| 10–20 s | 60 | 60 |
| 20–30 s | 200 | 152 |
| 30–40 s | 324 | 125 |
| 40–50 s | 224 | 41 |

The difficult early interval retains frequent checks; cleaner intervals receive most of the savings. This is a reduction in verification calls, not a measured end-to-end speedup.

## Limits and next experiment

- The six rejections are model outcomes, not independently human-labeled truth. Some accepted boxes are also poorly localized. Retaining all six does not prove safety.
- This replays the original optical trajectories. Skipping verification could change recovery, branch seeds and future boxes in a real run.
- The current tracker reinitializes features at propagation checkpoints. Feature-count ratios across those resets are only proxies, not true feature survival. A real adaptive implementation must preserve branch timing and define feature baseline/reinitialization semantics explicitly.
- Missing historical branch state conservatively requests a first check. Checks between originally measured positions are not evaluated.
- These are several intervals of one sailing video. They do not calibrate thresholds for skiing, occlusion, cuts or another camera.
- Small-target pixel residuals here are far below the proposed 0.75-pixel threshold. This dataset cannot validate that cutoff.

Start a controlled trial with **0.5 seconds for stable, well-localized crops**, 0.25 seconds for intermediate motion, and 0.1 seconds after weak/ambiguous/multiple-subject evidence (subject to configured maximum FPS). Keep independent recovery and identity acceptance rules unchanged. Compare actual trajectories and human-reviewed boxes before making it the default. Improve localization verification separately; more frequent checks alone do not correct the demonstrated false acceptances.

## Reproduction

Freeze complete lines of the run's `path_candidates.jsonl`, `optical_motion.jsonl` and `stage_usage.jsonl`, plus `meta.json`, `corrections.json` and `stage_store.json`, into a separate directory. The referenced stage-record store must remain accessible. Never evaluate by modifying the live run.

```bash
.venv/bin/python scripts/evaluate_verification_schedule.py /path/to/frozen/snapshot
```

The script writes `evaluation.json` in the supplied snapshot and prints results. Media, crop paths, stage records and snapshot data remain local runtime artifacts, outside version control.
