/* Coverage across three cadences, not a prediction of wall-time completion. */
window.TrackingProgressView={render(element,progress){
 element.replaceChildren();
 const text=(tag,value,parent=element)=>{const node=document.createElement(tag);node.textContent=value;parent.append(node);return node};
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
  if(group.attempts)text('small',`${number(group.attempts.total)} attempts (${number(group.attempts.accepted)} accepted, ${number(group.attempts.rejected)} rejected, ${number(group.attempts.errored)} errors) · ${number(group.attempts.cached)} cached reuses`,card);
  if(group.off_grid_examined)text('p',`${number(group.off_grid_examined)} additional off-grid positions`,card);
 }
 text('small','Coverage, not completion percentage. Positions count once; attempts include repeated visits and both verification paths. Crop acceptance requires confidence and completeness.');
 if(coverage.historical_incomplete)text('p',coverage.legacy?'This run predates detailed counters: verification and optical history were not recorded.':'Earlier work was not recorded by this version; coverage and attempts are partial.');
 if(coverage.stage==='complete')text('p','Scheduling complete. Adaptive tracking does not require every coverage counter to reach its denominator.');
}};
