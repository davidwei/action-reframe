/* Description editing lives in Video focus; library links to this section. */
window.DescriptionReview=(()=>{
 const $=id=>document.getElementById(id);let project=null,state=null,busy=false,dirty=false,token=0,autoAttempted=false;
 async function request(action,body){const r=await fetch('/api/batch/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await r.json();if(!r.ok)throw Error(result.error||r.status);return result}
 function status(text){$('descriptionStatus').textContent=text}
 function controls(){const readonly=!!state?.config?.batch_input_revision,hasBox=!!state?.config?.reference_box;
  $('descriptionText').disabled=busy||!project||readonly;
  $('draftDescription').disabled=busy||!project||!hasBox||readonly;
  $('saveDescription').disabled=busy||!project||readonly;
  $('approveDescription').disabled=busy||!project||!hasBox||readonly;
 }
 async function generate(){
  if(busy||!state?.config?.reference_box)return;
  const current=++token;busy=true;controls();status('Qwen is summarizing up to five labeled crops…');
  try{const result=await request('draft',{project});if(current!==token)return;$('descriptionText').value=result.description;dirty=true;status('Draft ready. Review and edit before approving.')}
  catch(e){status(e.message+' You can write the description manually.')}
  finally{if(current===token){busy=false;controls()}}
 }
 async function maybeDraft(){if(location.hash==='#identity-description'&&!autoAttempted&&!busy&&state?.config?.reference_box&&!state?.config?.batch_input_revision&&!$('descriptionText').value.trim()){autoAttempted=true;await generate()}}
 async function update(next){
  state=next;
  if(project!==next.project){
   project=next.project;const current=++token;dirty=false;busy=true;autoAttempted=false;controls();
   if(!project){$('descriptionText').value='';status('Create a project to save a description.');busy=false;controls();return}
   if(next.config.batch_input_revision){$('descriptionText').value=next.config.approved_target_description||'';status('Approved description for this saved run. Edit descriptions in its source project to prepare a new revision.');busy=false;controls();return}
   try{const response=await fetch('/api/batch');const data=await response.json();if(!response.ok)throw Error(data.error);if(current!==token)return;const p=data.projects.find(p=>p.project===project);$('descriptionText').value=p?.description||'';status(p?.ready?'Description approved for current inputs.':next.config.reference_box?'Review or draft the identity description.':'Write a draft, then label the subject before approving.')}
   finally{if(current===token){busy=false;controls()}}
  }
  controls();await maybeDraft();
 }
 $('descriptionText').oninput=()=>{dirty=true;status('Unsaved changes — save as draft or approve.')};
 $('draftDescription').onclick=()=>generate();
 for(const [id,ready] of [['saveDescription',false],['approveDescription',true]])$(id).onclick=async()=>{
  if(busy)return;busy=true;controls();
  try{await request('prepare',{project,description:$('descriptionText').value,ready});dirty=false;status(ready?'Description approved. Project is Ready in the library.':'Draft saved. Project is Draft in the library.')}
  catch(e){status(e.message)}finally{busy=false;controls()}
 };
 window.addEventListener('hashchange',()=>maybeDraft());
 window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue=''}});
 controls();
 return {update};
})();
