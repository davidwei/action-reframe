/* Shared run configuration summary. Values are text, never HTML. */
window.ConfigurationReview={update(element,state){
 const report=state.configuration_review;if(!element||!report)return;
 const signature=JSON.stringify(report);if(element._signature===signature)return;element._signature=signature;
 element.replaceChildren();
 const add=(parent,tag,text)=>{const node=document.createElement(tag);node.textContent=text;parent.append(node);return node};
 add(element,'h2','Configuration for this view');
 add(element,'p',`${state.project_name||'New project'} · ${report.scope}`);
 add(element,'p',`${report.outdated} outdated settings · ${report.attention} need attention. Red items require review; intentional overrides are labeled separately. Settings are not changed automatically.`);
 for(const [stage,code] of Object.entries(report.code)){
  const line=add(element,'p',`${stage==='analysis'?'Analysis':'Rendering'} code: ${code.label}${code.commit?' · '+code.commit.slice(0,8):''}`);
  if(code.status==='older')line.style.color='#ff8585';
 }
 const groups=new Map();
 for(const row of report.rows){
  let details=groups.get(row.group);
  if(!details){details=add(element,'details','');add(details,'summary',row.group);groups.set(row.group,details)}
  if(['outdated','attention'].includes(row.status))details.open=true;
  const line=add(details,'div','');line.style.cssText='padding:8px 0;border-bottom:1px solid #43505e;overflow-wrap:anywhere';
  if(['outdated','attention'].includes(row.status)){line.style.color='#ff8585';line.style.borderLeft='3px solid #ff8585';line.style.paddingLeft='10px'}
  const format=value=>value===undefined?'Not recorded':typeof value==='string'?value:JSON.stringify(value);
  add(line,'strong',row.key+' ');add(line,'span',format(row.value)+' · '+row.status);
  if(row.status==='outdated')add(line,'p','Current project: '+format(row.current));
  if(row.status==='override')add(line,'p','System default: '+format(row.default));
  if(row.reason)add(line,'p',row.reason);
 }
}};
