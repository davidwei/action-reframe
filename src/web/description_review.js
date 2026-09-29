/* Shared blind observations and identity checks; human approval stays explicit. */
window.DescriptionReview=(()=>{
 const $=id=>document.getElementById(id);let project=null,state=null,busy=false,dirty=false,token=0,review=null,remoteJob=null,revisions=[],lastPoll=0,polling=false;
 async function request(action,body){const r=await fetch('/api/batch/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await r.json();if(!r.ok){const error=Error(result.error||r.status);error.modelDetails=result.model_error;throw error;}return result}
 function status(text){$('descriptionStatus').textContent=text}
 function current(){return review?.description===$('descriptionText').value.trim()}
 function crops(){
  const parent=$('descriptionCrops');parent.replaceChildren();
  for(const r of review?.references||[]){
   const card=document.createElement('article');card.style.cssText='width:260px;padding:10px;border:1px solid #666;border-radius:6px';
   const image=document.createElement('img');image.src='/files/'+r.crop_path.split('/').map(encodeURIComponent).join('/');image.alt=(r.expected_present===false?'Frame marked absent: ':'Ground-truth crop at frame ')+r.frame;image.style.cssText='width:100%;height:150px;object-fit:contain';card.append(image);
   const add=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;card.append(e);return e};
   add('h3',`Frame ${r.frame} · ${r.time.toFixed(3)}s`);
   const absent=r.expected_present===false;
   add('p',absent?'Marked absent · full frame · expected confidence ≤20%':'Marked present · selected crop · expected confidence ≥80%');
   const valid=current()&&Number.isFinite(r.confidence);
   const score=add('p',valid?`Identity confidence: ${(r.confidence*100).toFixed(1)}% — ${r.passed?(absent?'Pass: low match as expected':'Pass'):(absent?'Unexpected match above 20%: review':'Below 80%: review / revise summary')}`:r.comparison?'Score outdated — check this description again.':'Not checked yet.');
   if(valid)score.style.color=r.passed?'#65dfab':'#ffba70';
   add('p',r.box_description||'Crop description will be generated when you draft or check.');
   if(valid){add('p',r.comparison.reason);if(r.comparison.differences.length)add('p','Differences / missing evidence: '+r.comparison.differences.join('; '));add('p','Complete object supported: '+(r.comparison.target_complete?'Yes':'No / uncertain'))}
   parent.append(card);
  }
 }
 function controls(){const blocked=busy||remoteJob?.status==='running',readonly=!!state?.config?.batch_input_revision,hasBox=!!state?.config?.reference_box;
  $('descriptionText').disabled=blocked||!project||readonly;
  for(const id of ['draftDescription','checkDescription','retryDescription','approveDescription'])$(id).disabled=blocked||!project||!hasBox||readonly;
  $('checkDescription').disabled=blocked||!project||readonly||!review?.references?.length||!$('descriptionText').value.trim();
  $('retryDescription').disabled ||= !current()||!review?.references?.some(r=>r.passed===false);
  $('saveDescription').disabled=blocked||!project||readonly;
  for(const id of ['restoreSavedDescription','restoreApprovedDescription','refreshDescriptionHistory','restoreDescriptionRevision','descriptionRevision'])$(id).disabled=blocked||!project||readonly;
  $('restoreSavedDescription').disabled ||= !revisions.length;
  $('restoreApprovedDescription').disabled ||= !revisions.some(r=>r.kind==='approved');
  $('restoreDescriptionRevision').disabled ||= !revisions.length;

 }
 function revisionPreview(){const r=revisions.find(r=>r.id===$('descriptionRevision').value);$('descriptionRevisionPreview').textContent=r?.description||''}
 async function refreshHistory(){
  if(!project||state?.config?.batch_input_revision)return;
  const selected=project,active=token;const result=await request('description-history',{project:selected});
  if(project!==selected||active!==token)return;
  revisions=result.revisions||[];const select=$('descriptionRevision'),previous=select.value;select.replaceChildren();
  for(const r of revisions){const option=document.createElement('option');option.value=r.id;option.textContent=`${new Date(r.created*1000).toLocaleString()} · ${r.kind==='approved'?'Approved':'Saved'}${r.source.startsWith('job:')?' (recovered run snapshot)':''}`;select.append(option)}
  if(revisions.some(r=>r.id===previous))select.value=previous;
  revisionPreview();controls();
 }
 function restoreRevision(revision){
  if(!revision||busy||remoteJob?.status==='running'||state?.config?.batch_input_revision)return;
  $('descriptionText').value=revision.description;dirty=true;crops();controls();
  status(`Restored ${revision.kind} revision from ${new Date(revision.created*1000).toLocaleString()} to the editor. Save or approve to keep it; no model call was made.`);
 }
 async function generate(action='draft'){
  if(busy||remoteJob?.status==='running'||!project||(action!=='check-description'&&!state?.config?.reference_box))return;
  $('descriptionErrorDetails').hidden=true;$('descriptionErrorText').textContent='';
  const active=++token;busy=true;controls();status(action==='draft'?'Qwen is describing all labeled crops, summarizing, and checking each crop…':action==='retry-description'?'Qwen is revising the summary using feedback, then rechecking each crop…':'Comparing each crop description with your edited description…');
  try{const result=await request(action,{project,description:$('descriptionText').value.trim()});if(active!==token)return;review=result;remoteJob=result.job||null;if(action!=='check-description'){$('descriptionText').value=result.description;dirty=true}crops();status(result.all_passed?'All positive and absent checks pass. Review and approve when satisfied.':'Some examples fail their expected confidence range. Review the scores, feedback and labels.');}
  catch(e){if(active===token){status(e.message);if(e.modelDetails){$('descriptionErrorDetails').hidden=false;$('descriptionErrorText').textContent=JSON.stringify(e.modelDetails,null,2)}}}
  finally{if(active===token){busy=false;controls()}}
 }
 async function refreshReview(){
  if(polling||busy||!project)return;const active=token,selected=project;polling=true;lastPoll=Date.now();
  try{const result=await request('description-status',{project:selected});if(active===token&&project===selected){
   const wasRunning=remoteJob?.status==='running';review=result;remoteJob=result.job||null;
   if(remoteJob?.status==='running')status(`Description ${remoteJob.action||'check'} is running for this project${remoteJob.started?' (started '+new Date(remoteJob.started*1000).toLocaleTimeString()+')':''}. Results will appear here when it finishes.`);
   else if(['failed','interrupted'].includes(remoteJob?.status)){status(remoteJob.error||'Description work failed. You can retry.');if(remoteJob.model_error){$('descriptionErrorDetails').hidden=false;$('descriptionErrorText').textContent=JSON.stringify(remoteJob.model_error,null,2)}}
   else if(wasRunning)status('Description work completed. Review the crop results below.');
   crops();controls()
  }}
  catch(e){if(active===token)status(e.message)}finally{polling=false}
 }
 async function update(next){
  state=next;
  if(project!==next.project){
   project=next.project;const active=++token;dirty=false;busy=true;review=null;remoteJob=null;crops();controls();
   if(!project){$('descriptionText').value='';status('Create a project to save a description.');busy=false;controls();return}
   try{
    if(next.config.batch_input_revision){$('descriptionText').value=next.config.approved_target_description||'';status('Approved description for this saved run. Edit its source project to prepare a new revision.')}
    else{const response=await fetch('/api/batch');const data=await response.json();if(!response.ok)throw Error(data.error);if(active!==token)return;const p=data.projects.find(p=>p.project===project);$('descriptionText').value=p?.description||'';status(p?.ready?'Description approved for current inputs.':'Review or draft the identity description.')}
   }catch(e){if(active===token)status(e.message)}finally{if(active===token)busy=false}
   await refreshReview();
   try{await refreshHistory()}catch(e){status(e.message)}
  }
  if(Date.now()-lastPoll>10000)await refreshReview();
  controls();
 }
 $('descriptionText').oninput=()=>{dirty=true;crops();controls();status('Unsaved changes — check against crops, then save or approve.')};
 $('draftDescription').onclick=()=>generate();$('checkDescription').onclick=()=>generate('check-description');$('retryDescription').onclick=()=>generate('retry-description');
 for(const [id,ready] of [['saveDescription',false],['approveDescription',true]])$(id).onclick=async()=>{
  if(busy||remoteJob?.status==='running')return;const active=++token;busy=true;controls();
  try{await request('prepare',{project,description:$('descriptionText').value,ready});if(active!==token)return;dirty=false;await refreshHistory();status((ready?'Description approved. Project is Ready in the library.':'Draft saved.')+(!current()?' Crop scores have not been checked for this description.':review?.all_passed?'':' Some examples fail their expected confidence range.'))}
  catch(e){if(active===token)status(e.message)}finally{if(active===token){busy=false;controls()}}
 };
 $('descriptionRevision').onchange=revisionPreview;
 $('refreshDescriptionHistory').onclick=()=>refreshHistory().catch(e=>status(e.message));
 $('restoreSavedDescription').onclick=()=>restoreRevision(revisions[0]);
 $('restoreApprovedDescription').onclick=()=>restoreRevision(revisions.find(r=>r.kind==='approved'));
 $('restoreDescriptionRevision').onclick=()=>restoreRevision(revisions.find(r=>r.id===$('descriptionRevision').value));
 window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});
 controls();return {update};
})();
