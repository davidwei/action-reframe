/* Coverage across three cadences, not a prediction of wall-time completion. */
window.TrackingProgressView={render(element,progress){
 element.replaceChildren();
 const text=(tag,value,parent=element)=>{const node=document.createElement(tag);node.textContent=value;parent.append(node);return node};
 const labels={discovery:'Discovery',crop_description:'Crop descriptions',identity_comparison:'Identity comparisons',acceptance:'Acceptance decisions',optical_tracking:'Optical tracking',camera_path:'Camera path'};
 if(progress?.stage_reuse){
  text('strong','Stage reuse');
  for(const [stage,counts] of Object.entries(progress.stage_reuse))text('p',`${labels[stage]||stage}: ${counts.computed} computed · ${counts.reused} reused`);
 }
 const coverage=progress?.coverage;
 if(!coverage){if(progress?.stage)text('span',`${progress.stage}: ${progress.completed??'?'} / ${progress.total??'?'}`);return}
 const number=value=>Number.isFinite(value)?value.toLocaleString():'?';
 text('p',`${coverage.stage||progress.stage} · ${number(coverage.anchors)} anchors · ${number(coverage.pending_propagation)} pending propagation tasks`);
 const grid=document.createElement('div');grid.style.cssText='display:flex;flex-wrap:wrap;gap:12px';element.append(grid);
 for(const [kind,title,verb,rate] of [
  ['discovery','Discovery','scanned',progress.discovery_fps],
  ['verification','Crop verification','checked',progress.analysis_fps],
  ['optical','Optical tracking','visited',progress.source_fps]]){
  const group=coverage[kind],card=document.createElement('div');card.style.cssText='flex:1;min-width:170px;padding:10px;border:1px solid #526274;border-radius:6px';grid.append(card);
  text('strong',title+(rate?` (${Number(rate).toLocaleString(undefined,{maximumFractionDigits:2})} FPS)`:(kind==='optical'?' (source FPS)':'')),card);
  if(!group?.available){text('p',`Not recorded · ${number(group?.total)} possible positions`,card);continue}
  text('p',`${number(group.examined)} / ${number(group.total)} unique positions ${verb}`,card);
  if(kind==='discovery')text('p',`${number(group.resolved_without_scan)} resolved without scanning · ${number(group.remaining)} remaining`,card);
  if(group.accepted!==undefined)text('p',`${number(group.accepted)} ${kind==='optical'?'usable':'accepted'} · ${number(group.rejected)} ${kind==='optical'?'unusable':'rejected'} · ${number(group.errored)} errored positions`,card);
  if(group.rejection_reasons){const r=group.rejection_reasons;text('p',`${number(r.identity_rejected)} identity rejected · ${number(r.localization_rejected)} localization rejected · ${number(r.request_error)} request errors${r.unclassified?` · ${number(r.unclassified)} other/unclassified`:''}`,card)}
  const confidence=group.confidence;
  if(confidence){
   text('p',`${number(confidence.passed)} medium or higher (≥${Math.round(confidence.threshold*100)}%) · ${number(confidence.high)} high / anchor-eligible (≥${Math.round(confidence.anchor_threshold*100)}%)`,card);
   text('small',`Confidence recorded for ${number(confidence.recorded)} positions. High is a subset of medium or higher.`,card);
   if(kind==='optical')text('p','Only crop-verified motion checkpoints have object confidence; optical-only frames are unverified. Independent localization is required for anchors.',card);
  }else text('p','Confidence counts not recorded for this run.',card);
  if(group.attempts)text('small',`${number(group.attempts.total)} attempts (${number(group.attempts.accepted)} accepted, ${number(group.attempts.rejected)} rejected, ${number(group.attempts.errored)} errors) · ${number(group.attempts.cached)} cached reuses`,card);
  if(group.off_grid_examined)text('p',`${number(group.off_grid_examined)} additional off-grid positions`,card);
 }
 text('small','Coverage, not completion percentage. Positions count once; attempts include repeated visits and both verification paths. New crop acceptance requires identity confidence and supported localization; partial visibility is allowed. Older runs retain their recorded decisions.');
 if(coverage.historical_incomplete)text('p',coverage.legacy?'This run predates detailed counters: verification and optical history were not recorded.':'Earlier work was not recorded by this version; coverage and attempts are partial.');
 if(coverage.stage==='complete')text('p','Scheduling complete. Adaptive tracking does not require every coverage counter to reach its denominator.');
}};
