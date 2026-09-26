/* Shared frame diagnostics for the selection and synchronized comparison pages. */
(() => {
  const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : 'not available';
  const percent = value => Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'not available';
  const vector = value => Array.isArray(value) ? `[${value.map(v => number(v, 1)).join(', ')}]` : 'not available';
  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);

  function describe(state, frame, sourceMatches = true) {
    const meta = state.meta || {};
    const fps = meta.fps;
    if (!sourceMatches) return {status: 'No analysis for this source', tone: 'neutral', confidence: null,
      text: 'Select the project’s source video, or create and analyze a project for this video.', data: null};
    const track = state.tracks?.[frame] || null;
    const observations = state.observations || [];
    let previous = null, next = null;
    for (const observation of observations) {
      if (observation.frame <= frame && (!previous || observation.frame > previous.frame)) previous = observation;
      if (observation.frame >= frame && (!next || observation.frame < next.frame)) next = observation;
    }
    const nearest = !previous ? next : !next ? previous :
      frame - previous.frame <= next.frame - frame ? previous : next;
    const exact = nearest?.frame === frame;
    const correction = state.corrections?.[frame] || null;
    const confidence = !nearest?.manual && Number.isFinite(nearest?.confidence) ? nearest.confidence : null;
    const flags = track?.flags || [];
    const box = track?.bbox;
    let status = 'No frame analysis', tone = 'neutral';
    if (track) {
      if (!box) { status = 'Lost / not confidently located'; tone = 'lost'; }
      else if (flags.some(f => /target|identity|appearance|visibility|reidentification|vl_error/.test(f)) ||
               (confidence !== null && confidence < .65)) {
        status = 'Target located — needs review'; tone = 'uncertain';
      } else { status = 'Target tracked'; tone = 'tracked'; }
    } else if (nearest) {
      status = exact ? (nearest.bbox && confidence >= .65 ? 'Detected — not rendered' : 'Lost / uncertain observation') :
        'Between observations — no per-frame track yet';
      tone = exact ? (nearest.bbox && confidence >= .65 ? 'tracked' : 'lost') : 'neutral';
    }
    const rawBox = nearest?.bbox && meta.width && meta.height ? nearest.bbox.map((v, i) => v / 1000 * (i % 2 ? meta.height : meta.width)) : null;
    const cropWidth = Number.isFinite(track?.crop_height) && state.config?.output_height ?
      track.crop_height * state.config.output_width / state.config.output_height : null;
    const lines = [
      `Frame: ${frame} (zero-based) | Time: ${number(fps ? frame / fps : null, 3)} s`,
      `Source dimensions: ${meta.width || '?'} × ${meta.height || '?'} px`,
      `Source playback rate: ${number(meta.fps,3)} FPS | Analysis sampling rate for this run: ${number(meta.analysis_fps,3)} FPS`,
      `Tracking status: ${status}`,
      `Observation source: ${nearest?.manual ? 'manual label' : nearest?.backward_recovered ? 'backward recovery pass' : nearest?.recovered ? 'first-pass small-target recovery' : nearest ? 'first pass' : 'not available'}`,
      '',
      `Object box used for render [left, top, right, bottom]: ${box ? vector(box) + ' px' : 'none'}`,
      `Object center: ${box ? vector([(box[0]+box[2])/2, (box[1]+box[3])/2]) + ' px' : 'not available'}`,
      `Object size: ${box ? `${number(box[2]-box[0],1)} × ${number(box[3]-box[1],1)} px` : 'not available'}`,
      '',
      `Leveling angle used for render: ${number(track?.roll)}°`,
      'Leveling source: visual shoreline estimate, not verified gravity/IMU data.',
      'Angle convention: positive = source shoreline slopes down to the right; correction rotates counterclockwise.',
      `Crop center in source: ${vector(track?.center)} px`,
      `Crop size in source coordinates: ${number(cropWidth,1)} × ${number(track?.crop_height,1)} px`,
      `Zoom relative to source height: ${number(track?.zoom)}×`,
      `Review flags: ${flags.length ? flags.join(', ') : track ? 'none recorded (not a guarantee of accuracy)' : 'not available'}`,
      '',
      nearest ? `Qwen observation: frame ${nearest.frame}, ${number(nearest.time ?? (fps ? nearest.frame / fps : null),3)} s (${exact ? 'direct observation of this frame' : `nearest sampled frame; offset ${number(fps ? (nearest.frame-frame)/fps : null,3)} s`})` : 'Qwen observation: not available',
      `Object confidence at that observation: ${percent(confidence)} (model-reported, not calibrated)`,
      `Visibility at that observation: ${nearest?.visibility || 'not available'}`,
      `Qwen box in source pixels: ${vector(rawBox)}`,
      `Qwen box in normalized 0–1000 coordinates: ${vector(nearest?.bbox)}`,
      `Level confidence at that observation: ${percent(nearest?.level_confidence)}`,
      `Shoreline endpoints [x1, y1, x2, y2], normalized 0–1000: ${vector(nearest?.shoreline)}`,
      `Model note: ${nearest?.note || 'none'}`,
      `Level explanation: ${nearest?.level_note || 'none recorded'}`,
      ...(nearest?.temporal_context ? [
        `Temporal context: ${nearest.temporal_context.direction}; ${nearest.temporal_context.history_count} prior sampled frames`,
        `History sent individually: ${nearest.temporal_context.individual_record_count}; summarized: ${nearest.temporal_context.summarized_record_count}`,
        `History images represented: ${nearest.temporal_context.visual_frame_count}; images omitted for context limits: ${nearest.temporal_context.unsent_visual_frame_count}`,
        `Qwen input tokens: ${nearest.temporal_context.input_tokens} / ${nearest.temporal_context.context_limit}`
      ] : []),
      ...(nearest?.backward_attempt ? [
        `Backward attempt: ${nearest.backward_attempt.accepted ? 'accepted' : 'not accepted'}`,
        `Backward seed: frame ${nearest.backward_attempt.seed_frame}; interval-end seed: frame ${nearest.backward_attempt.interval_seed_frame}`,
        `Backward confidence: ${percent(nearest.backward_attempt.evidence?.confidence)}`,
        `Backward evidence: ${nearest.backward_attempt.evidence?.note || 'none'}`
      ] : []),
      ...(nearest?.first_pass_tracking ? [`First-pass confidence before recovery: ${percent(nearest.first_pass_tracking.confidence)}`] : []),
      ...(nearest?.recovery_note ? [`Re-identification note: ${nearest.recovery_note}`] : []),
      ...(nearest?.recovery_rejected ? [`Re-identification rejected: ${nearest.recovery_rejected}`] : []),
      ...(nearest?.error || nearest?.recovery_error ? [`Analysis error: ${nearest.error || nearest.recovery_error}`] : []),
      '',
      correction ? 'Saved manual correction at this frame (separate from rendered values; rerender to apply new edits):' : 'Manual correction at this frame: none',
      ...(own(correction, 'bbox') ? [`  Object: ${correction.bbox === null ? 'marked absent' : vector(correction.bbox)+' px'}`] : []),
      ...(own(correction, 'roll') ? [`  Level angle: ${number(correction.roll)}°`] : []),
      '',
      'Confidence belongs to the labeled Qwen observation. No separate calibrated per-frame tracking confidence is stored.'
    ];
    return {status, tone, confidence, text: lines.join('\n'), data: {
      frame, time_seconds: fps ? frame/fps : null, rendered_track: track,
      nearest_observation: nearest, observation_is_exact_frame: exact,
      preceding_observation: previous, following_observation: next, saved_manual_correction: correction
    }};
  }

  const style = document.createElement('style');
  style.textContent = `.frame-analysis{margin:18px 0;padding:18px;background:#192531;border:1px solid #425567;border-radius:10px}.frame-analysis h2{margin:0 0 12px;font-size:20px}.analysis-indicators{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:12px}.analysis-badge{padding:6px 10px;border-radius:6px;background:#344555}.analysis-badge[data-tone=tracked]{background:#205642}.analysis-badge[data-tone=uncertain]{background:#70501b}.analysis-badge[data-tone=lost]{background:#792e3b}.analysis-confidence{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.analysis-confidence meter{width:140px}.frame-analysis textarea{box-sizing:border-box;width:100%;height:360px;resize:vertical;font:13px/1.55 ui-monospace,monospace;padding:12px;background:#0e1822;color:#e2edf6;border:1px solid #476074;border-radius:6px}.frame-analysis summary{cursor:pointer;margin:12px 0}.frame-analysis label{display:block;margin-bottom:8px}.frame-analysis .analysis-json{height:300px}`;
  document.head.append(style);
  function update(element, state, frame, options = {}) {
    if (!element) return;
    if (!element.dataset.mounted) {
      element.classList.add('frame-analysis'); element.dataset.mounted = 'true';
      element.innerHTML = `<h2>Frame analysis</h2><div class="analysis-indicators"><span class="analysis-badge"></span><span class="analysis-confidence"><span class="analysis-score"></span><meter min="0" max="1" low="0.65" high="0.85" optimum="1" aria-label="Nearest Qwen object confidence"></meter></span></div><label>Analysis for the displayed frame<textarea class="analysis-text" readonly spellcheck="false" aria-label="Frame analysis results"></textarea></label><details><summary>All stored values (JSON)</summary><textarea class="analysis-json" readonly spellcheck="false" aria-label="Complete frame analysis JSON"></textarea></details>`;
    }
    const result = describe(state, frame, options.sourceMatches !== false);
    const badge = element.querySelector('.analysis-badge'); badge.textContent = result.status; badge.dataset.tone = result.tone;
    element.querySelector('.analysis-score').textContent = `Nearest Qwen confidence: ${percent(result.confidence)}`;
    const meter = element.querySelector('meter'); meter.hidden = result.confidence === null; meter.value = result.confidence ?? 0;
    element.querySelector('.analysis-text').value = result.text;
    element.querySelector('.analysis-json').value = JSON.stringify(result.data, null, 2);
  }
  window.FrameAnalysis = {describe, update};
})();
