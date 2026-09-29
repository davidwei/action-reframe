# Agreed decisions

- Follow the selected subject; the initial sailing example targets the other boat, not the camera boat. The architecture and prompts must generalize beyond that example.
- Offline processing and frequent model use are acceptable. Preserve source footage, evidence and prior successful results for review.
- Blur and strong zoom are acceptable; smooth framing is preferred. The user selects useful segments afterward.
- Feather missing borders into a blurred extension. Generative enhancement is future work.
- Human boxes and absence are authoritative. Description edits require explicit action; drawing a label must not automatically rewrite the description.
- Use blind crop descriptions and approved identity text for verification. Keep identity confidence, localization quality and motion quality separate. Allow partial/blurred targets.
- Retain reliable unverified optical motion for framing; relax ambiguous localization only, without lowering the configured identity threshold.
- Maintain independent raw and gyro-leveled optical branches. Use each branch's preceding selected box center as its rotation pivot; without a usable previous box, use the raw image center.
- Discover/recover at no more than 2 FPS per branch; verify crops at configurable cadence; propagate optical motion through source frames in both directions.
- Keep all four candidate types. Select branch seeds by eligible crop confidence and select the final render candidate across branches. No rendering zoom during analysis.
- Interpolate output zoom between framing boxes, with nominal 1× endpoints. Rotation-aware edge coverage constrains zoom; the minimum crop short side (180 source pixels by default) takes priority when constraints conflict, using blurred fill.
- Organize the product as four components, video scheduling and folder workflow. Prepare inputs, process offline and review outputs; a separate planner/trial approval experience remains planned.

## Adjustable new-project defaults

10 FPS crop verification, 2 FPS discovery, 50% acceptance, 85% priority anchors, gyro leveling, 1280×720 output, approximately 55% subject height and blurred/feathered borders. Visual/gyro divergence is highlighted above 5°. Existing project overrides and queued snapshots are preserved.

See [current approach](CURRENT_APPROACH.md), [video paths](TWO_PATH_TRACKING.md) and [architecture roadmap](ARCHITECTURE_ROADMAP.md) for behavior, limits and next steps.
