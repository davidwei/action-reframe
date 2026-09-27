/* Shared frame diagnostics for the selection and synchronized comparison pages. */
(() => {
  const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : 'not available';
  const percent = value => Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'not available';
  const vector = value => Array.isArray(value) ? `[${value.map(v => number(v, 1)).join(', ')}]` : 'not available';
  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);
  function verificationLines(row,label) {
    if(!row)return [];
    const v=row.box_verification;
    return [
      ...(row.verification_retry_count!=null?[`${label} crop-verification retries: ${row.verification_retry_count} | attempts: ${row.detection_attempts?.length||1} (all attempts in JSON)`]:[]),
      `${label} box_note: ${row.box_note||'not recorded'}`,
      ...(v?[
        `${label} independent crop description: ${v.description?.box_description||v.error||'not available'}`,
        `${label} crop evidence: target present=${v.description?.target_present??'?'}; complete=${v.description?.target_complete??'?'}; verifier confidence=${percent(v.description?.confidence)}`,
        `${label} note/crop consistency: ${percent(v.comparison?.consistency)} | differences: ${v.comparison?.differences?.join('; ')||'none recorded'}`,
        `${label} confidence: original=${percent(row.model_confidence)}; adjusted=${percent(row.confidence)} (conservative heuristic, not calibrated probability)`
      ]:[])
    ];
  }
  function directionLines(row,label) {
    if(!row)return [];
    const comparison=row.direction_comparison;
    return [
      `${label} chosen direction: ${row.direction_choice||row.direction||'forward'} | ${row.direction_reason||'forward pass'}`,
      ...(comparison?[
        `${label} forward box: ${vector(comparison.forward.bbox)} | verified confidence ${percent(comparison.forward.confidence)}`,
        `${label} backward box: ${vector(comparison.backward.bbox)} | verified confidence ${percent(comparison.backward.confidence)}`,
        `${label} direction comparison: source-normalized boxes; IoU ${number(comparison.box_iou,3)}; flags ${row.direction_flags?.join(', ')||'none'}`,
        `${label} direction adjudication: ${comparison.adjudication?.reason||comparison.adjudication?.error||'not needed'}`
      ]:[])
    ];
  }

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
    const confidence = correction && own(correction,'bbox') ? (correction.bbox ? 1 : 0) : nearest?.manual ? nearest.confidence : !nearest?.manual && Number.isFinite(nearest?.confidence) ? nearest.confidence : null;
    const flags = track?.flags || [];
    const level = track?.level_source ? track : state.level_comparison?.[frame];
    const box = track?.bbox;
    const dualRows=state.tracking_comparison||[];
    const dual=dualRows.reduce((best,row)=>!best||Math.abs(row.frame-frame)<Math.abs(best.frame-frame)?row:best,null);
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
    if(own(correction,'bbox')){status=correction.bbox?'Human-confirmed target — saved':'Human-confirmed absence — saved';tone=correction.bbox?'tracked':'lost';}
    const rawBox = nearest?.bbox && meta.width && meta.height ? nearest.bbox.map((v, i) => v / 1000 * (i % 2 ? meta.height : meta.width)) : null;
    const cropWidth = Number.isFinite(track?.crop_height) && state.config?.output_height ?
      track.crop_height * state.config.output_width / state.config.output_height : null;
    const lines = [
      `Frame: ${frame} (zero-based) | Time: ${number(fps ? frame / fps : null, 3)} s`,
      `Result: ${state.config?.output_dir || 'not available'}`,
      `Leveling source: ${level?.level_source==='gyro'?'DJI fused attitude (gyro-derived); final render uses telemetry':'legacy visual estimate; this result does not use gyro leveling'}`,
      `Leveling angle used for render: ${number(track?.roll)}°`,
      ...(level ? [
        `Gyro-derived roll: ${number(level.gyro_roll)}° | Qwen independent visual roll: ${number(level.qwen_roll)}°`,
        `Qwen minus gyro: ${number(level.level_difference)}° | warning threshold: ${number(level.level_divergence_threshold)}°`
      ] : []),
      '',
      ...(dual ? [
        `TRACKING PATH COMPARISON — sampled frame ${dual.frame}, offset ${number(fps?(dual.frame-frame)/fps:null,3)} s (not a fresh detection at every playback frame)`,
        `Selected path at sample: ${dual.selected?.selected_path||'not selected in this run'}${dual.selected?.path_switched?' — PATH SWITCH':''}`,
        `Selection reason: ${dual.selected?.selection_reason||'not available'}`,
        `Selection flags: ${dual.selected?.selection_flags?.join(', ')||'none'}`,
        `Adjudication: ${dual.selected?.adjudication?JSON.stringify(dual.selected.adjudication,(key,value)=>['raw','temporal_context'].includes(key)?undefined:value):'not needed'}`,
        `Rendered frame tracking source: ${track?.selected_path||'not recorded'} | interpolation sample frames: ${track?.selection_source_samples?.join(', ')||'not recorded'} | contributing paths: ${track?.selection_source_paths?.join(', ')||'not recorded'}`,
        `Both paths use normalized 0–1000 ORIGINAL source coordinates. Box overlap (IoU): ${number(dual.box_iou,3)}`,
        `Gyro angle supplied to both paths: ${number(dual.raw_angle.gyro_roll)}° | render path: ${state.config?.tracking_render_path||'raw_angle'}`,
        '',
        'RAW PATH — cyan',
        `Raw + angle: box ${vector(dual.raw_angle.bbox)} | confidence ${percent(dual.raw_angle.confidence)} | ${dual.raw_angle.visibility} | ${dual.raw_angle.direction}`,
        `Raw path evidence: ${dual.raw_angle.note||dual.raw_angle.error||'none'}`,
        ...directionLines(dual.raw_angle,'Raw path'),
        ...verificationLines(dual.raw_angle,'Raw path'),
        '',
        'LEVELED PATH — orange',
        `Leveled image → source: box ${vector(dual.leveled.bbox)} | confidence ${percent(dual.leveled.confidence)} | ${dual.leveled.visibility} | ${dual.leveled.direction}`,
        `Leveled path evidence: ${dual.leveled.note||dual.leveled.error||'none'}`,
        ...directionLines(dual.leveled,'Leveled path'),
        ...verificationLines(dual.leveled,'Leveled path'),
        ''
      ] : []),
      `Source dimensions: ${meta.width || '?'} × ${meta.height || '?'} px`,
      `Source playback rate: ${number(meta.fps,3)} FPS | Analysis sampling rate for this run: ${number(meta.analysis_fps,3)} FPS`,
      `Tracking status: ${status}`,
      `Observation source: ${nearest?.manual ? 'manual label' : nearest?.backward_recovered ? 'backward recovery pass' : nearest?.recovered ? 'first-pass small-target recovery' : nearest ? 'first pass' : 'not available'}`,
      '',
      `Object box used for render [left, top, right, bottom]: ${box ? vector(box) + ' px' : 'none'}`,
      `Object center: ${box ? vector([(box[0]+box[2])/2, (box[1]+box[3])/2]) + ' px' : 'not available'}`,
      `Object size: ${box ? `${number(box[2]-box[0],1)} × ${number(box[3]-box[1],1)} px` : 'not available'}`,
      '',
      ...(level ? [
        `Comparison: ${level.level_divergent?'DIVERGENCE — review':level.qwen_roll==null?'visual estimate unavailable':'within threshold'}`,
        `Qwen level sample: frame ${level.qwen_level_frame??'?'} (offset ${number(fps&&level.qwen_level_frame!=null?(level.qwen_level_frame-frame)/fps:null,3)} s); ${level.qwen_level_frame===frame?'direct':'nearest sampled frame, not an independent per-frame measurement'}`,
        `Visual cue: ${level.qwen_level_cue} | orientation confidence: ${percent(level.qwen_level_confidence)} | model-reported confidence: ${percent(level.qwen_level_model_confidence)}`,
        `Visual evidence: ${level.qwen_level_note||'none'}${level.qwen_level_error?' | '+level.qwen_level_error:''}`,
        `Telemetry calibration: ${level.gyro_calibration}`
      ] : []),
      'Angle convention: positive = source shoreline slopes down to the right; correction rotates counterclockwise.',
      `Crop center in source: ${vector(track?.center)} px`,
      `Crop size in source coordinates: ${number(cropWidth,1)} × ${number(track?.crop_height,1)} px`,
      `Zoom relative to source height: ${number(track?.zoom)}×`,
      `Review flags: ${flags.length ? flags.join(', ') : track ? 'none recorded (not a guarantee of accuracy)' : 'not available'}`,
      '',
      nearest ? `Qwen observation: frame ${nearest.frame}, ${number(nearest.time ?? (fps ? nearest.frame / fps : null),3)} s (${exact ? 'direct observation of this frame' : `nearest sampled frame; offset ${number(fps ? (nearest.frame-frame)/fps : null,3)} s`})` : 'Qwen observation: not available',
      `Object confidence at that observation: ${percent(confidence)} (${nearest?.confidence_source==='crop_verified_heuristic'?'crop-verified heuristic':'model-reported'}; not calibrated)`,
      `Visibility at that observation: ${nearest?.visibility || 'not available'}`,
      `Qwen box in source pixels: ${vector(rawBox)}`,
      `Qwen box in normalized 0–1000 coordinates: ${vector(nearest?.bbox)}`,
      `Legacy tracking-pass level confidence (not independent leveling): ${percent(nearest?.level_confidence)}`,
      `Legacy tracking-pass shoreline endpoints (not final gyro leveling): ${vector(nearest?.shoreline)}`,
      `Model note: ${nearest?.note || 'none'}`,
      `Legacy tracking-pass level explanation: ${nearest?.level_note || 'none recorded'}`,
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
      ...(own(correction, 'roll') ? [`  Level angle: ${number(correction.roll)}°${level?.level_source==='gyro'?' (not applied: gyro is final)':''}`] : []),
      '',
      'Human target boxes carry 100% confidence as an explicit user label, not a model probability. Other confidence values belong to the nearest tracking observation.'
    ];
    return {status, tone, confidence, level, text: lines.join('\n'), data: {
      frame, time_seconds: fps ? frame/fps : null, rendered_track: track,
      level_comparison:level||null, tracking_comparison:dual, nearest_observation: nearest, observation_is_exact_frame: exact,
      preceding_observation: previous, following_observation: next, saved_manual_correction: correction
    }};
  }

  function boxForLine(result, line, state) {
    const d=result.data;if(!d)return null;
    const width=state.meta?.width,height=state.meta?.height;
    const pixels=box=>box?.map((v,i)=>v*(i%2?height:width)/1000);
    let box,frame=d.frame,label,color='#ffe066';
    if(line.startsWith('Raw + angle: box')) {box=pixels(d.tracking_comparison?.raw_angle.bbox);frame=d.tracking_comparison?.frame;label='Raw + angle';color='#00e5ff';}
    else if(line.startsWith('Leveled image → source: box')) {box=pixels(d.tracking_comparison?.leveled.bbox);frame=d.tracking_comparison?.frame;label='Leveled → original';color='#ff9f32';}
    else if(line.startsWith('Object box used for render')) {box=d.rendered_track?.bbox;label='Box used for render';}
    else if(line.startsWith('Qwen box in ')) {box=pixels(d.nearest_observation?.bbox);frame=d.nearest_observation?.frame;label='Qwen observation';}
    else if(line.startsWith('  Object:')) {box=d.saved_manual_correction?.bbox;label='Saved manual correction';}
    else {
      for(const [key,name] of [['raw_angle','Raw path'],['leveled','Leveled path']])for(const direction of ['forward','backward']){
        if(line.startsWith(`${name} ${direction} box:`)){
          box=pixels(d.tracking_comparison?.[key]?.direction_comparison?.[direction]?.bbox);
          frame=d.tracking_comparison?.frame;label=`${name} ${direction}`;color=key==='raw_angle'?'#00e5ff':'#ff9f32';
        }
      }
      if(!label)return null;
    }
    const valid=Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1];
    return {box:valid?box:null,frame,label,color,width,height,video:state.config?.video};
  }

  async function inspectBox(element, result, state) {
    const text=element.querySelector('.analysis-text');
    const line=text.value.slice(0,text.selectionStart).split('\n').length-1;
    const item=boxForLine(result,text.value.split('\n')[line]||'',state);
    if(!item)return;
    const preview=element.querySelector('.analysis-box-preview'),caption=element.querySelector('.analysis-box-caption');
    const token=Symbol();element._boxToken=token;preview.hidden=false;
    const image=element.querySelector('.analysis-box-image'),svg=element.querySelector('.analysis-box-overlay');
    image.hidden=true;svg.replaceChildren();
    if(!item.box){caption.textContent=`${item.label}: no box available for this frame.`;element.dispatchEvent(new CustomEvent('analysis-box',{bubbles:true,detail:item}));return;}
    caption.textContent=`${item.label} — original frame ${item.frame}, ${(item.frame/state.meta.fps).toFixed(3)} s. Loading…`;
    try {
      const fresh=new Image();fresh.src='/api/frame?video='+encodeURIComponent(item.video)+'&frame='+item.frame;await fresh.decode();
      if(element._boxToken!==token)return;
      image.src=fresh.src;image.hidden=false;
      svg.setAttribute('viewBox',`0 0 ${item.width} ${item.height}`);
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      const [x1,y1,x2,y2]=item.box;
      for(const [key,value] of Object.entries({x:x1,y:y1,width:x2-x1,height:y2-y1,fill:'none',stroke:item.color,'stroke-width':4,'vector-effect':'non-scaling-stroke'}))rect.setAttribute(key,value);
      svg.append(rect);
      caption.textContent=`${item.label} — original frame ${item.frame}, ${(item.frame/state.meta.fps).toFixed(3)} s. Inspection only; the selected tracking path is unchanged.`;
      element.dispatchEvent(new CustomEvent('analysis-box',{bubbles:true,detail:item}));
    } catch(error) {if(element._boxToken===token)caption.textContent='Could not load frame: '+error.message;}
  }

  const style = document.createElement('style');
  style.textContent = `.frame-analysis{margin:18px 0;padding:18px;background:#192531;border:1px solid #425567;border-radius:10px}.frame-analysis h2{margin:0 0 12px;font-size:20px}.analysis-indicators{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:12px}.analysis-badge{padding:6px 10px;border-radius:6px;background:#344555}.analysis-badge[data-tone=tracked]{background:#205642}.analysis-badge[data-tone=uncertain]{background:#70501b}.analysis-badge[data-tone=lost]{background:#792e3b}.analysis-confidence{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.analysis-confidence meter{width:140px}.frame-analysis textarea{box-sizing:border-box;width:100%;height:360px;resize:vertical;font:13px/1.55 ui-monospace,monospace;padding:12px;background:#0e1822;color:#e2edf6;border:1px solid #476074;border-radius:6px}.frame-analysis summary{cursor:pointer;margin:12px 0}.frame-analysis label{display:block;margin-bottom:8px}.frame-analysis .analysis-json{height:300px}`;
  style.textContent += `.analysis-box-preview{margin:12px 0}.analysis-box-picture{position:relative;max-width:960px}.analysis-box-image{display:block;width:100%}.analysis-box-overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.analysis-box-hint{font-size:13px;color:#b1c5d4}`;
  document.head.append(style);
  function update(element, state, frame, options = {}) {
    if (!element) return;
    if (!element.dataset.mounted) {
      element.classList.add('frame-analysis'); element.dataset.mounted = 'true';
      element.innerHTML = `<h2>Frame analysis</h2><div class="analysis-indicators"><span class="analysis-badge"></span><span class="analysis-level analysis-badge"></span><span class="analysis-confidence"><span class="analysis-score"></span><meter min="0" max="1" low="0.65" high="0.85" optimum="1" aria-label="Nearest Qwen object confidence"></meter></span></div><label>Analysis for the displayed frame<textarea class="analysis-text" readonly spellcheck="false" aria-label="Frame analysis results"></textarea></label><p class="analysis-box-hint">Available Raw (cyan) and Leveled (orange) boxes appear automatically on the source view. Click a box-coordinate line for an additional inspection. Keyboard: place the caret on the line and press Enter.</p><div class="analysis-box-preview" hidden><p class="analysis-box-caption" role="status"></p><div class="analysis-box-picture"><img class="analysis-box-image" alt="Original frame with the inspected bounding box"><svg class="analysis-box-overlay"></svg></div><button type="button" class="analysis-box-clear">Clear highlight</button></div><details><summary>All stored values (JSON)</summary><textarea class="analysis-json" readonly spellcheck="false" aria-label="Complete frame analysis JSON"></textarea></details>`;
    }
    const result = describe(state, frame, options.sourceMatches !== false);
    const badge = element.querySelector('.analysis-badge'); badge.textContent = result.status; badge.dataset.tone = result.tone;
    const levelBadge=element.querySelector('.analysis-level');
    levelBadge.hidden=!result.level;
    if(result.level){const l=result.level;levelBadge.textContent=`Gyro ${number(l.gyro_roll)}° · Qwen ${number(l.qwen_roll)}° · Δ ${number(l.level_difference)}°${l.level_divergent?' — DIVERGENCE':''}`;levelBadge.dataset.tone=l.level_divergent?'lost':l.qwen_roll==null?'uncertain':'neutral';}
    element.querySelector('.analysis-score').textContent = `Tracking confidence: ${percent(result.confidence)}${state.corrections?.[frame] && own(state.corrections[frame],'bbox') || result.data?.nearest_observation?.manual ? ' (human label)' : ''}`;
    const meter = element.querySelector('meter'); meter.hidden = result.confidence === null; meter.value = result.confidence ?? 0;
    const text=element.querySelector('.analysis-text');
    if(element._analysisFrame!==frame){element._boxToken=null;element.querySelector('.analysis-box-preview').hidden=true;}
    element._analysisFrame=frame;
    text.value = result.text;
    text.onpointerdown=()=>document.querySelectorAll('video').forEach(video=>video.pause());
    text.onclick=()=>inspectBox(element,result,state);
    text.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();inspectBox(element,result,state);}};
    element.querySelector('.analysis-box-clear').onclick=()=>{element._boxToken=null;element.querySelector('.analysis-box-preview').hidden=true;element.dispatchEvent(new CustomEvent('analysis-box',{bubbles:true,detail:null}));};
    element.querySelector('.analysis-json').value = JSON.stringify(result.data, null, 2);
  }
  function playbackBoxes(state, frame) {
    const rows=state.tracking_comparison||[],meta=state.meta||{};
    if(!rows.length||!meta.width||!meta.height)return [];
    let lo=0,hi=rows.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(rows[mid].frame<frame)lo=mid+1;else hi=mid;}
    const left=rows[Math.max(0,lo-1)],right=rows[Math.min(rows.length-1,lo)];
    const step=meta.fps/(meta.analysis_fps||state.config?.analysis_fps||2);
    const nearest=Math.abs(frame-left.frame)<=Math.abs(right.frame-frame)?left:right;
    const valid=r=>Array.isArray(r?.bbox)&&r.bbox.length===4&&r.bbox.every(Number.isFinite)&&r.bbox[2]>r.bbox[0]&&r.bbox[3]>r.bbox[1]&&!r.error;
    const points=(row,path)=>{
      const r=row[path];if(!valid(r))return null;
      if(path==='raw_angle'&&r.source_polygon_px?.length===4&&r.source_polygon_px.every(p=>p.length===2&&p.every(Number.isFinite)))return r.source_polygon_px;
      const [x1,y1,x2,y2]=r.bbox.map((v,i)=>v*(i%2?meta.height:meta.width)/1000);
      return [[x1,y1],[x2,y1],[x2,y2],[x1,y2]];
    };
    return ['raw_angle','leveled'].flatMap(path=>{
      let polygon,interpolated=false;
      const a=points(left,path),b=points(right,path);
      if(a&&b&&left.frame<frame&&frame<right.frame&&right.frame-left.frame<=step*1.5){
        const weight=(frame-left.frame)/(right.frame-left.frame);
        polygon=a.map((point,i)=>point.map((v,j)=>v+(b[i][j]-v)*weight));interpolated=true;
      }else if(Math.abs(nearest.frame-frame)<=Math.max(1,step/2+.5))polygon=points(nearest,path);
      return polygon?[{path,polygon,interpolated,sampleFrame:nearest.frame}]:[];
    });
  }
  window.FrameAnalysis = {describe, update, boxForLine, playbackBoxes};
})();
