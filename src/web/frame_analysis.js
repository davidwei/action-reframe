/* Shared frame diagnostics for the selection and synchronized comparison pages. */
(() => {
  const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : 'not available';
  const percent = value => Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'not available';
  const vector = value => Array.isArray(value) ? `[${value.map(v => number(v, 1)).join(', ')}]` : 'not available';
  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);
  const acceptedEvidence = row => row?.manual || !(row?.box_verification?.version>=7) || row.box_verification.decision?.accepted===true;
  function trackingMethod(row, fallback = null) {
    if(!row)return 'not recorded';
    if(row.manual)return 'human label';
    if(row.analysis_source==='optical_unverified')return 'Optical motion used for framing; identity unverified';
    const source=row.analysis_source||fallback?.analysis_source;
    if(source==='flow_crop_validation')return 'Optical flow + crop validation (no Qwen localization)';
    if(source==='local_detection')return 'Qwen localization inside a search region';
    if(source==='full_frame_detection')return 'Independent Qwen full-frame detection';
    if(row.qwen_view_bbox!==undefined||row.temporal_context)return 'Independent Qwen detection';
    return source||'not recorded';
  }
  function pathMethodLines(row,label,selected){
    const v=row?.box_verification;
    const score=v?.version>=2 ? (v.identity_score??(v.comparison?.target_present===false?0:v.comparison?.match_score)) : null;
    return [
      `${label} box method: ${trackingMethod(row,selected)}`,
      `${label} text-comparison confidence: ${percent(score)}${v?.version>=2?' (identity reliability, not box-boundary accuracy)':'; current identity score unavailable for this result'}`,
      ...(row?.analysis_source==='flow_crop_validation'?[`${label} optical motion quality: ${percent(row.motion_quality)} | uncertainty: ${number(row.motion_uncertainty_px)} px; separate from identity confidence`]:[])
    ];
  }
  function humanLabel(state,frame){
    const correction=state.corrections?.[frame];if(own(correction,'bbox'))return correction;
    const row=state.observations?.find(r=>r.frame===frame);
    if(!row?.manual)return null;
    return {...row,bbox:row.bbox?row.bbox.map((v,i)=>v*(i%2?state.meta.height:state.meta.width)/1000):null};
  }
  function renderedBox(state,frame){
    if(own(state.corrections?.[frame],'bbox'))return null;
    const row=state.observations?.find(r=>r.frame===frame)||state.tracking_comparison?.find(r=>r.frame===frame)?.selected;
    const box=row?.bbox,meta=state.meta||{};
    return row?.analysis_source!=='optical_unverified'&&!row?.manual&&!row?.error&&Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1]
      ?box.map((v,i)=>v*(i%2?meta.height:meta.width)/1000):null;
  }
  function verificationLines(row,label) {
    if(!row)return [];
    const v=row.box_verification;
    return [
      ...(row.verification_retry_count!=null?[`${label} crop-verification retries: ${row.verification_retry_count} | attempts: ${row.detection_attempts?.length||1} (all attempts in JSON)`]:[]),
      `${label} box_note: ${row.box_note||'not recorded'}`,
      ...(v?.version>=2?[
        `${label} trusted target description: ${v.reference_description?.target_description||'not available'}`,
        `${label} blind crop description: ${v.description?.box_description||v.error||'not available'}`,
        `${label} text-match identity score: ${percent(v.identity_score)} | model match score: ${percent(v.comparison?.match_score)} | target present=${v.comparison?.target_present??'?'} | box complete=${v.comparison?.target_complete??'?'}`,
        ...(v.version>=7?[
          `${label} crop viewpoint: ${v.description?.viewpoint||'unclear'} | composition: ${v.description?.composition||'unclear'} | visibility: ${v.description?.visibility||'unclear'} (model observations)`,
          `${label} localization: ${v.comparison?.localization_support||'unclear'} — ${v.comparison?.localization_reason||'not recorded'}`,
          `${label} identity exclusions: ${v.comparison?.exclusion_check||'unclear'} — ${v.comparison?.exclusion_reason||'not recorded'}`,
          `${label} verification decision: ${v.decision?.category||'not recorded'} — ${v.decision?.reason||v.error||'not recorded'}${v.decision?` (threshold ${percent(v.decision.threshold)})`:''}`
        ]:[]),
        `${label} match evidence: ${v.comparison?.reason||'not available'} | differences: ${v.comparison?.differences?.join('; ')||'none recorded'}`,
        `${label} confidence used: ${percent(row.confidence)} (text-match reliability, not calibrated probability); detector self-score: ${percent(row.model_confidence)} (diagnostic only)`
      ]:v?[
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
    const meta=state.meta||{},fps=meta.fps,threshold=state.config?.tracking_selection?.confidence_threshold??.5;
    if(!sourceMatches)return {status:'No analysis for this source',tone:'neutral',confidence:null,confidenceSource:'no analysis for this source',text:'Select the project’s source video.',data:null};
    const track=state.tracks?.[frame]||null;
    const dual=state.tracking_comparison?.find(r=>r.frame===frame)||null;
    const observation=state.observations?.find(r=>r.frame===frame)||dual?.selected||null;
    const correction=state.corrections?.[frame]||null;
    const human=own(correction,'bbox')||observation?.manual;
    const humanBox=own(correction,'bbox')?correction.bbox:observation?.bbox;
    const flow=observation?.analysis_source==='flow_crop_validation';
    const path=observation?.selected_path||observation?.path||track?.selected_path;
    const pathName=path==='raw_angle'?'raw':path==='leveled'?'leveled':path==='manual'?'human':'raw/leveled';
    const optical=opticalPrediction(state,frame);
    let confidenceSource;
    if(human)confidenceSource=humanBox?'human label':'human label — target absent';
    else if(observation?.analysis_source==='optical_unverified')confidenceSource='unverified optical motion — usable for framing, not verified identity';
    else if(flow)confidenceSource=`tracking with ${pathName} analysis (optical flow + crop validation)`;
    else if(observation)confidenceSource=`independent ${pathName} analysis${observation.analysis_source==='local_detection'?' (local search)':''}${!observation.bbox?' — no accepted box':''}`;
    else if(optical)confidenceSource='optical motion prediction — before crop validation';
    else if(track?.bbox)confidenceSource=`interpolated/held tracking from ${pathName} analysis — no analysis at this frame`;
    else confidenceSource='no analysis at this frame';
    const confidence=human?(humanBox?1:0):(Number.isFinite(observation?.confidence)?observation.confidence:null);
    let status=human?(humanBox?'Human-confirmed target':'Human-confirmed absence'):observation?.analysis_source==='optical_unverified'?'Optical framing (identity unverified)':observation?(observation.bbox&&confidence>=threshold&&acceptedEvidence(observation)?'Target located':'Lost / uncertain observation'):optical?(optical.reliable?'Optical prediction (unverified)':'Optical motion failed'):track?.bbox?'Interpolated/held tracking box':'No direct tracking analysis';
    const tone=human?(humanBox?'tracked':'lost'):confidence!==null?(confidence>=threshold&&acceptedEvidence(observation)?'tracked':'uncertain'):'neutral';
    const storedLevel=track?.level_source?track:state.level_comparison?.[frame];
    const directVisual=storedLevel?.qwen_level_frame===frame;
    // Do not put a neighboring frame's visual-level estimate into this frame's badge.
    const level=storedLevel?{...storedLevel,...(!directVisual?{qwen_roll:null,level_difference:null,level_divergent:false}:{})}:null;
    const box=track?.bbox;
    const lines=[
      `Frame: ${frame} (zero-based) | Time: ${number(fps?frame/fps:null,3)} s`,
      `Result: ${state.config?.output_dir||'not available'}`,
      `Tracking confidence: ${percent(confidence)} — ${confidenceSource}`,
      ...Object.entries(state.path_candidates?.[frame]||{}).flatMap(([key,r])=>[
        `${key}: crop identity ${percent(r.confidence)} (${r.confidence_measurement||'measured'}${r.confidence_measurement==='inherited'?' from frame '+r.confidence_frame:''}); motion quality ${percent(r.motion_quality)}`,
        ...(r.verification_region?[`${key} verification evidence: expanded image context; detection box retained separately`]:[]),
        ...(r.verification_schedule?[`${key} verification: ${r.verification_schedule.performed?'performed':'not performed'}; ${r.verification_schedule.reason}; mode ${r.verification_schedule.mode}; proposed check ${r.verification_schedule.proposed_verify?'yes':'no'}`,
          `${key} box size: ${vector(r.verification_schedule.box_pixels)} px; tiny: ${r.verification_schedule.tiny?'yes':'no'} (<${r.verification_schedule.tiny_threshold_px} px); last passed identity frame ${r.verification_schedule.last_pass_frame??'unknown'}, age ${number(r.verification_schedule.identity_age_seconds)} s`]:[]),
        `${key} source-normalized box: ${vector(r.bbox)} | ${r.box_verification?.decision?.reason||r.motion_reason||'No fresh verification at this frame'}`]),
      ...(optical?[`Optical prediction before crop validation: ${optical.reliable?'available (magenta dotted box)':'motion failed; no prediction box'}`,
        `Optical box [left, top, right, bottom] in raw pixels: ${vector(optical.bbox_px)}`,
        `Optical source: frame ${optical.source_frame??'not recorded'} | ${optical.direction||'unknown'} | motion quality ${percent(optical.motion_quality)} (not identity confidence)`,
        `Optical features: ${optical.feature_count??'not recorded'} | ${optical.reason||'Crop acceptance is separate; this overlay does not imply verified identity.'}`]:[]),
      ...(!observation&&!human?['No independent detection or crop-validation score is stored for this frame. Neighboring sampled-frame analyses are not shown.']:[]),
      '',
      `Object box used for render [left, top, right, bottom]: ${box?vector(box)+' px':'none'}`,
      ...(box?[
        `Rendered box provenance: ${track.selection_is_direct===false?'interpolated/held estimate, not a fresh detection':'saved frame track'}`,
        `Contributing sample frames: ${track.selection_source_samples?.join(', ')||'not recorded'} | contributing paths: ${track.selection_source_paths?.join(', ')||'not recorded'}`,
        `Object center: ${vector([(box[0]+box[2])/2,(box[1]+box[3])/2])} px`,
        `Object size: ${number(box[2]-box[0],1)} × ${number(box[3]-box[1],1)} px`
      ]:[]),
      ...(observation?[
        '',`Analysis performed at this frame: ${trackingMethod(observation,dual?.selected)}`,
        `Analyzed box in normalized 0–1000 source coordinates: ${vector(observation.bbox)}`,
        `Visibility: ${observation.visibility||'not recorded'}`,
        ...(observation.origin_anchor!=null?[
          `Origin anchor: frame ${observation.origin_anchor} | parent: ${observation.parent_frame??'none'} | direction: ${observation.direction||'anchor'}`,
          `Localization: ${observation.localized?'localized box':'propagated estimate'}`
        ]:[]),
        ...(observation.motion_quality!=null?[
          `Optical motion quality: ${percent(observation.motion_quality)} | uncertainty: ${number(observation.motion_uncertainty_px)} px`,
          `Search region (source pixels): ${vector(observation.search_region_px)}`
        ]:[]),
        ...(observation.error?[`Analysis error: ${observation.error}`]:[])
      ]:[]),
      ...(dual?[
        '',`TRACKING PATH COMPARISON — this frame (${frame})`,
        `Selected path: ${dual.selected?.selected_path||'not selected'} | ${dual.selected?.selection_reason||'not recorded'}`,
        `Selection flags: ${dual.selected?.selection_flags?.join(', ')||'none'}`,
        `Box overlap (IoU): ${number(dual.box_iou,3)}. Both paths use normalized 0–1000 ORIGINAL source coordinates.`,
        '', 'RAW PATH — cyan',
        `Raw + angle: box ${vector(dual.raw_angle?.bbox)} | confidence ${percent(dual.raw_angle?.confidence)}`,
        ...pathMethodLines(dual.raw_angle,'Raw path',dual.selected),
        `Raw path evidence: ${dual.raw_angle?.note||dual.raw_angle?.error||'none'}`,
        ...directionLines(dual.raw_angle,'Raw path'),...verificationLines(dual.raw_angle,'Raw path'),
        '', 'LEVELED PATH — orange',
        `Leveled image → source: box ${vector(dual.leveled?.bbox)} | confidence ${percent(dual.leveled?.confidence)}`,
        ...pathMethodLines(dual.leveled,'Leveled path',dual.selected),
        `Leveled path evidence: ${dual.leveled?.note||dual.leveled?.error||'none'}`,
        ...directionLines(dual.leveled,'Leveled path'),...verificationLines(dual.leveled,'Leveled path')
      ]:observation&&!human?verificationLines(observation,'Tracking'):[]),
      '',
      ...(state.analysis_failures||[]).filter(r=>r.frame===frame).flatMap(r=>r.failures.map(f=>`Analysis failed (${f.path}): ${f.error}`)),
      `Leveling angle used for render: ${number(track?.roll)}°`,
      ...(level?[`Gyro-derived roll at this frame: ${number(level.gyro_roll)}°`]:[]),
      ...(directVisual?[
        `Qwen visual roll at this frame: ${number(level.qwen_roll)}° | Qwen minus gyro: ${number(level.level_difference)}°`,
        `Visual cue: ${level.qwen_level_cue||'not recorded'} | confidence: ${percent(level.qwen_level_confidence)}`,
        `Visual evidence: ${level.qwen_level_note||'none'}`
      ]:[]),
      ...(track?[`Render crop center: ${vector(track.center)} | crop size: ${number(track.crop_width)} × ${number(track.crop_height)} px; minimum short side ${number(track.minimum_crop_short_side)} px | zoom: ${number(track.zoom)}×`,`Zoom limits: ${number(track.zoom_min)}× minimum for edge coverage / ${number(track.zoom_max)}× maximum for subject fit${track.zoom_constraints_conflict?" — CONFLICT: minimum crop size takes priority when recorded; missing borders are filled":""}`,`Zoom smoothing: ${number(track.zoom_seconds_per_doubling)} s per 2× change; log smoothing ${number(track.zoom_smoothing_seconds)} s${track.zoom_edge_coverage_relaxed?' — edge coverage relaxed for smooth framing; background fill used':''}`,`Render flags: ${track.flags?.join(', ')||'none'}`]:[]),
      ...(correction?['','Saved manual correction at this frame (rerender to apply):',
        ...(own(correction,'bbox')?[`  Object: ${correction.bbox===null?'marked absent':vector(correction.bbox)+' px'}`]:[]),
        ...(correction.source_polygon_px?[`  Source polygon (pixels): ${JSON.stringify(correction.source_polygon_px)}`]:[]),
        ...(own(correction,'roll')?[`  Level angle: ${number(correction.roll)}°`]:[])] : [])
    ];
    return {status,tone,confidence,confidenceSource,level,text:lines.join('\n'),data:{
      frame,time_seconds:fps?frame/fps:null,rendered_track:track,tracking_comparison:dual,
      frame_observation:observation,nearest_observation:observation,observation_is_exact_frame:!!observation,
      four_path_candidates:state.path_candidates?.[frame]||null,saved_manual_correction:correction,level_comparison:level
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
    else if(line.startsWith('Analyzed box in ')) {box=pixels(d.nearest_observation?.bbox);frame=d.nearest_observation?.frame;label='Analyzed observation';}
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
      for(const [key,value] of Object.entries({x:x1,y:y1,width:x2-x1,height:y2-y1,fill:'none',stroke:item.color,'stroke-width':4,'stroke-dasharray':'7 4','vector-effect':'non-scaling-stroke'}))rect.setAttribute(key,value);
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
      element.innerHTML = `<h2>Frame analysis</h2><div class="analysis-indicators"><span class="analysis-badge"></span><span class="analysis-level analysis-badge"></span><span class="analysis-confidence"><span class="analysis-score"></span><meter min="0" max="1" low="0.65" high="0.85" optimum="1" aria-label="Tracking confidence at this frame"></meter></span></div><div class="analysis-approval" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px"><button type="button" data-approve="raw_angle">Approve Cyan (raw path)</button><button type="button" data-approve="leveled">Approve Orange (leveled path)</button><button type="button" data-approve="optical">Approve Magenta (tracking path)</button><button type="button" class="analysis-mark-absent">Mark target absent</button><span class="analysis-approval-status" role="status"></span></div><label>Analysis for the displayed frame<textarea class="analysis-text" readonly spellcheck="false" aria-label="Frame analysis results"></textarea></label><p class="analysis-box-hint">Available Raw (cyan) and Leveled (orange) boxes appear automatically on the source view. Click a box-coordinate line for an additional inspection. Keyboard: place the caret on the line and press Enter.</p><div class="analysis-box-preview" hidden><p class="analysis-box-caption" role="status"></p><div class="analysis-box-picture"><img class="analysis-box-image" alt="Original frame with the inspected bounding box"><svg class="analysis-box-overlay"></svg></div><button type="button" class="analysis-box-clear">Clear highlight</button></div><details><summary>All stored values (JSON)</summary><textarea class="analysis-json" readonly spellcheck="false" aria-label="Complete frame analysis JSON"></textarea></details>`;
    }
    const result = describe(state, frame, options.sourceMatches !== false);
    const displayed=[...playbackBoxes(state,frame),...opticalPlaybackBoxes(state,frame)];
    for(const button of element.querySelectorAll('[data-approve]')){
      const path=button.dataset.approve,candidate=displayed.find(box=>box.path===path);
      button.disabled=options.sourceMatches===false||!candidate?.polygon;
      button.title=candidate?.polygon?'Approve the displayed box regardless of confidence':'No box displayed for this path at this frame';
      button.onclick=async()=>{
        const message=element.querySelector('.analysis-approval-status');button.disabled=true;message.textContent='Saving…';
        try{
          const response=await fetch('/api/correct',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:state.project||new URLSearchParams(location.search).get('config'),frame,approve_path:path,polygon:candidate.polygon,approval_estimate:{interpolated:candidate.interpolated,sample_frame:candidate.sampleFrame}})});
          const value=await response.json();if(!response.ok)throw Error(value.error||response.status);
          message.textContent='Approved as human label (100%). '+(state.running?'Saved during processing; reanalyze or render afterward to apply.':'Reanalyze or render to apply.');
          element.dispatchEvent(new CustomEvent('analysis-approved',{bubbles:true,detail:{frame,path}}));
        }catch(error){message.textContent=error.message;}finally{button.disabled=options.sourceMatches===false||!candidate?.polygon;}
      };
    }

    const absent=element.querySelector('.analysis-mark-absent');
    absent.disabled=options.sourceMatches===false||!state.project||!state.meta||!Number.isInteger(frame)||frame<0||frame>=state.meta.frames;
    absent.onclick=async()=>{
      const message=element.querySelector('.analysis-approval-status');absent.disabled=true;message.textContent='Saving absence…';
      try{
        const response=await fetch('/api/correct',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:state.project,frame,bbox:null})});
        const value=await response.json();if(!response.ok)throw Error(value.error||response.status);
        message.textContent='Human-confirmed absence saved. Reanalyze or render to apply.';
        element.dispatchEvent(new CustomEvent('analysis-approved',{bubbles:true,detail:{frame,absent:true}}));
      }catch(error){message.textContent=error.message;}finally{absent.disabled=options.sourceMatches===false||!state.project;}
    };

    const badge = element.querySelector('.analysis-badge'); badge.textContent = result.status; badge.dataset.tone = result.tone;
    const levelBadge=element.querySelector('.analysis-level');
    levelBadge.hidden=!result.level;
    if(result.level){const l=result.level;levelBadge.textContent=`Gyro ${number(l.gyro_roll)}° · Qwen ${number(l.qwen_roll)}° · Δ ${number(l.level_difference)}°${l.level_divergent?' — DIVERGENCE':''}`;levelBadge.dataset.tone=l.level_divergent?'lost':l.qwen_roll==null?'uncertain':'neutral';}
    element.querySelector('.analysis-score').textContent = `Tracking confidence: ${percent(result.confidence)} — ${result.confidenceSource}`;
    const meter = element.querySelector('meter'); meter.hidden = result.confidence === null; meter.value = result.confidence ?? 0;meter.low=state.config?.tracking_selection?.confidence_threshold??.5;meter.high=Math.max(meter.low,.85);
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
  function opticalPrediction(state, frame) {
    const opticalCandidates=Object.values(state.path_candidates?.[frame]||{}).filter(r=>r.candidate_id?.endsWith('_optical')&&r.motion_reliable&&r.bbox).sort((a,b)=>b.confidence-a.confidence);
    if(opticalCandidates.length&&state.meta){const r=opticalCandidates[0];return {...r,reliable:true,bbox_px:r.bbox.map((v,i)=>v*(i%2?state.meta.height:state.meta.width)/1000),origin:r.path+' optical branch'}}
    const direct=state.optical_motion?.[frame];
    if(direct)return direct;
    // Historical runs retained checkpoint predictions inside propagation validation.
    const pair=state.tracking_comparison?.find(r=>r.frame===frame);
    const row=state.observations?.find(r=>r.frame===frame)||pair?.selected;
    const candidates=row?.propagation_validation||pair?.selected?.propagation_validation||{};
    const estimate=Object.values(candidates).find(r=>r.analysis_source==='flow_crop_validation'&&r.bbox);
    const flow=estimate||(row?.analysis_source==='flow_crop_validation'?row:null);
    if(!flow?.bbox||!state.meta?.width||!state.meta?.height)return null;
    return {frame,bbox_px:flow.bbox.map((v,i)=>v*(i%2?state.meta.height:state.meta.width)/1000),reliable:true,
      motion_quality:flow.motion_quality,source_frame:row?.parent_frame,direction:flow.direction,origin:'saved propagation checkpoint'};
  }
  function opticalBox(state, frame) {
    const prediction=opticalPrediction(state,frame),box=prediction?.bbox_px;
    return prediction?.reliable&&Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1]?box:null;
  }
  function opticalPlaybackBoxes(state,frame) {
    const box=opticalBox(state,frame);if(!box)return [];
    const [x1,y1,x2,y2]=box;
    return [{path:'optical',polygon:[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],interpolated:false,sampleFrame:frame}];
  }
  function playbackBoxes(state, frame) {
    let row=state.tracking_comparison?.find(r=>r.frame===frame);const meta=state.meta||{};
    const saved=state.path_candidates?.[frame];
    if(saved){row={};for(const path of ['raw_angle','leveled'])row[path]=Object.values(saved).filter(r=>r.path===path&&r.bbox&&!r.error).sort((a,b)=>b.confidence-a.confidence)[0]}

    if(!row||!meta.width||!meta.height)return [];
    return ['raw_angle','leveled'].flatMap(path=>{
      const r=row[path],box=r?.bbox;
      if(r?.manual||r?.error||!Array.isArray(box)||box.length!==4||!box.every(Number.isFinite)||box[2]<=box[0]||box[3]<=box[1])return [];
      let polygon;
      if(path==='raw_angle'&&r.source_polygon_px?.length>=3&&r.source_polygon_px.every(p=>p.length===2&&p.every(Number.isFinite)))polygon=r.source_polygon_px;
      else {const [x1,y1,x2,y2]=box.map((v,i)=>v*(i%2?meta.height:meta.width)/1000);polygon=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]];}
      return [{path,polygon,interpolated:false,sampleFrame:frame}];
    });
  }
  function navigationTargets(state, frame) {
    const reviewed=Object.keys(state.corrections||{}).map(Number);
    const sampled=state.meta?.samples ?? (state.tracking_comparison?.length ? state.tracking_comparison : state.observations||[]).filter(r=>!r.manual && !r.raw_angle?.manual).map(r=>r.frame);
    const threshold=state.config?.tracking_selection?.confidence_threshold??.5;
    const rows=new Map((state.observations||[]).map(r=>[r.frame,r]));
    for(const pair of state.tracking_comparison||[])if(pair.selected)rows.set(pair.frame,{...pair.selected,frame:pair.frame});
    for(const [i,c] of Object.entries(state.corrections||{}))if(Object.prototype.hasOwnProperty.call(c,'bbox'))rows.set(Number(i),{frame:Number(i),bbox:c.bbox,confidence:c.bbox?1:0,visibility:c.bbox?'visible':'absent'});
    const tracked=[...rows.values()].filter(r=>r.bbox&&r.confidence>=threshold&&acceptedEvidence(r)&&!r.error&&!r.scene_cut&&!['absent','uncertain'].includes(r.visibility)).map(r=>r.frame);
    const result={};
    for(const [kind,values] of Object.entries({reviewed,sampled,tracked})){
      const frames=[...new Set(values)].filter(i=>Number.isInteger(i)&&i>=0&&(!state.meta?.frames||i<state.meta.frames)).sort((a,b)=>a-b);
      result['previous'+kind]=frames.filter(i=>i<frame).at(-1)??null;
      result['next'+kind]=frames.find(i=>i>frame)??null;
    }
    return result;
  }
  function updateNavigation(element,state,frame,seek,enabled=true){
    if(!element.dataset.mounted){
      element.dataset.mounted='true';
      for(const direction of ['previous','next']){
        const group=document.createElement('fieldset');group.style.cssText='display:flex;gap:8px;flex-wrap:wrap;border:1px solid #526274;border-radius:8px;padding:10px';
        const legend=document.createElement('legend');legend.textContent=direction==='previous'?'Previous':'Next';group.append(legend);
        const kinds=direction==='previous'?['reviewed','tracked','sampled','frame']:['frame','sampled','tracked','reviewed'];
        for(const kind of kinds){
          const button=kind==='frame'?document.getElementById(direction):document.createElement('button');
          if(!button)continue;
          button.type='button';button.textContent=kind[0].toUpperCase()+kind.slice(1);
          button.setAttribute('aria-label',`${legend.textContent} ${kind==='frame'?'frame':kind+' frame'}`);
          button.dataset.lookoutAction=`frame.${direction}_${kind}`;
          if(kind!=='frame')button.dataset.target=direction+kind;
          group.append(button);
        }
        element.append(group);
      }
      element.title='Reviewed: saved manual corrections, including target absent. Sampled: analysis sampling schedule. Tracked: accepted target box at this exact frame (including human labels), not interpolated framing.';
    }
    const targets=navigationTargets(state,frame);
    for(const button of element.querySelectorAll('button[data-target]')){
      const target=targets[button.dataset.target];button.disabled=!enabled||target===null;
      button.title=target===null?'No matching frame in this direction':`Frame ${target}${state.meta?.fps?' · '+(target/state.meta.fps).toFixed(3)+' s':''}`;
      button.onclick=()=>{if(enabled&&target!==null)seek(target);};
    }
  }
  window.FrameAnalysis = {describe, update, boxForLine, opticalPrediction, opticalBox, opticalPlaybackBoxes, playbackBoxes, navigationTargets, updateNavigation, renderedBox, humanLabel, trackingMethod};
})();
