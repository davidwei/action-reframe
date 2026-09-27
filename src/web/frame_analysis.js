/* Shared frame diagnostics for the selection and synchronized comparison pages. */
(() => {
  const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : 'not available';
  const percent = value => Number.isFinite(value) ? `${Math.round(value * 100)}%` : 'not available';
  const vector = value => Array.isArray(value) ? `[${value.map(v => number(v, 1)).join(', ')}]` : 'not available';
  const own = (object, key) => object != null && Object.prototype.hasOwnProperty.call(object, key);
  function trackingMethod(row, fallback = null) {
    if(!row)return 'not recorded';
    if(row.manual)return 'human label';
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
  function renderedBox(state,frame){
    const box=state.tracks?.[frame]?.bbox;
    return Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1]?box:null;
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
        `${label} text-match identity score: ${percent(v.identity_score)} | target present=${v.comparison?.target_present??'?'} | box complete=${v.comparison?.target_complete??'?'}`,
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
    let confidenceSource;
    if(human)confidenceSource=humanBox?'human label':'human label — target absent';
    else if(flow)confidenceSource=`tracking with ${pathName} analysis (optical flow + crop validation)`;
    else if(observation)confidenceSource=`independent ${pathName} analysis${observation.analysis_source==='local_detection'?' (local search)':''}${!observation.bbox?' — no accepted box':''}`;
    else if(track?.bbox)confidenceSource=`interpolated/held tracking from ${pathName} analysis — no analysis at this frame`;
    else confidenceSource='no analysis at this frame';
    const confidence=human?(humanBox?1:0):(Number.isFinite(observation?.confidence)?observation.confidence:null);
    let status=human?(humanBox?'Human-confirmed target':'Human-confirmed absence'):observation?(observation.bbox&&confidence>=threshold?'Target located':'Lost / uncertain observation'):track?.bbox?'Interpolated/held tracking box':'No direct tracking analysis';
    const tone=human?(humanBox?'tracked':'lost'):confidence!==null?(confidence>=threshold?'tracked':'uncertain'):'neutral';
    const storedLevel=track?.level_source?track:state.level_comparison?.[frame];
    const directVisual=storedLevel?.qwen_level_frame===frame;
    // Do not put a neighboring frame's visual-level estimate into this frame's badge.
    const level=storedLevel?{...storedLevel,...(!directVisual?{qwen_roll:null,level_difference:null,level_divergent:false}:{})}:null;
    const box=track?.bbox;
    const lines=[
      `Frame: ${frame} (zero-based) | Time: ${number(fps?frame/fps:null,3)} s`,
      `Result: ${state.config?.output_dir||'not available'}`,
      `Tracking confidence: ${percent(confidence)} — ${confidenceSource}`,
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
      `Leveling angle used for render: ${number(track?.roll)}°`,
      ...(level?[`Gyro-derived roll at this frame: ${number(level.gyro_roll)}°`]:[]),
      ...(directVisual?[
        `Qwen visual roll at this frame: ${number(level.qwen_roll)}° | Qwen minus gyro: ${number(level.level_difference)}°`,
        `Visual cue: ${level.qwen_level_cue||'not recorded'} | confidence: ${percent(level.qwen_level_confidence)}`,
        `Visual evidence: ${level.qwen_level_note||'none'}`
      ]:[]),
      ...(track?[`Render crop center: ${vector(track.center)} | crop height: ${number(track.crop_height)} px | zoom: ${number(track.zoom)}×`,`Render flags: ${track.flags?.join(', ')||'none'}`]:[]),
      ...(correction?['','Saved manual correction at this frame (rerender to apply):',
        ...(own(correction,'bbox')?[`  Object: ${correction.bbox===null?'marked absent':vector(correction.bbox)+' px'}`]:[]),
        ...(own(correction,'roll')?[`  Level angle: ${number(correction.roll)}°`]:[])] : [])
    ];
    return {status,tone,confidence,confidenceSource,level,text:lines.join('\n'),data:{
      frame,time_seconds:fps?frame/fps:null,rendered_track:track,tracking_comparison:dual,
      frame_observation:observation,nearest_observation:observation,observation_is_exact_frame:!!observation,
      saved_manual_correction:correction,level_comparison:level
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
      element.innerHTML = `<h2>Frame analysis</h2><div class="analysis-indicators"><span class="analysis-badge"></span><span class="analysis-level analysis-badge"></span><span class="analysis-confidence"><span class="analysis-score"></span><meter min="0" max="1" low="0.65" high="0.85" optimum="1" aria-label="Tracking confidence at this frame"></meter></span></div><label>Analysis for the displayed frame<textarea class="analysis-text" readonly spellcheck="false" aria-label="Frame analysis results"></textarea></label><p class="analysis-box-hint">Available Raw (cyan) and Leveled (orange) boxes appear automatically on the source view. Click a box-coordinate line for an additional inspection. Keyboard: place the caret on the line and press Enter.</p><div class="analysis-box-preview" hidden><p class="analysis-box-caption" role="status"></p><div class="analysis-box-picture"><img class="analysis-box-image" alt="Original frame with the inspected bounding box"><svg class="analysis-box-overlay"></svg></div><button type="button" class="analysis-box-clear">Clear highlight</button></div><details><summary>All stored values (JSON)</summary><textarea class="analysis-json" readonly spellcheck="false" aria-label="Complete frame analysis JSON"></textarea></details>`;
    }
    const result = describe(state, frame, options.sourceMatches !== false);
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
  function navigationTargets(state, frame) {
    const reviewed=Object.keys(state.corrections||{}).map(Number);
    const sampled=state.meta?.samples ?? (state.tracking_comparison?.length ? state.tracking_comparison : state.observations||[]).filter(r=>!r.manual && !r.raw_angle?.manual).map(r=>r.frame);
    const result={};
    for(const [kind,values] of Object.entries({reviewed,sampled})){
      const frames=[...new Set(values)].filter(i=>Number.isInteger(i)&&i>=0&&(!state.meta?.frames||i<state.meta.frames)).sort((a,b)=>a-b);
      result['previous'+kind]=frames.filter(i=>i<frame).at(-1)??null;
      result['next'+kind]=frames.find(i=>i>frame)??null;
    }
    return result;
  }
  function updateNavigation(element,state,frame,seek,enabled=true){
    if(!element.dataset.mounted){
      element.dataset.mounted='true';
      for(const kind of ['reviewed','sampled'])for(const direction of ['previous','next']){
        const button=document.createElement('button');button.type='button';button.dataset.target=direction+kind;
        button.textContent=`${direction==='previous'?'Previous':'Next'} ${kind} frame`;
        element.append(button);
      }
      element.title='Reviewed: saved manual corrections, including target absent. Sampled: analysis sampling schedule.';
    }
    const targets=navigationTargets(state,frame);
    for(const button of element.querySelectorAll('button')){
      const target=targets[button.dataset.target];button.disabled=!enabled||target===null;
      button.title=target===null?'No matching frame in this direction':`Frame ${target}${state.meta?.fps?' · '+(target/state.meta.fps).toFixed(3)+' s':''}`;
      button.onclick=()=>{if(enabled&&target!==null)seek(target);};
    }
  }
  window.FrameAnalysis = {describe, update, boxForLine, playbackBoxes, navigationTargets, updateNavigation, renderedBox, trackingMethod};
})();
