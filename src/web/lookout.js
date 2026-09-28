/* Local activity summaries only: no pointer coordinates, keystrokes or text. */
(()=>{
 const originalFetch=window.fetch.bind(window),session=crypto.randomUUID(),workflow=crypto.randomUUID();
 const page=location.pathname==='/library'?'folder':location.pathname==='/compare'?'comparison':'focus';
 let pendingSeek=0,enabled=false,buffer=[],lastActivity=Date.now(),mouse=false,keyboard=false,lastBucket=Date.now(),lastAction='',lastScroll=0;
 const labels={'Add project':'project.add','Refresh folder':'folder.refresh','Start / resume queue':'queue.start','Pause after current video':'queue.pause','Stop processing':'job.stop','Retry saved inputs':'job.retry','Cancel':'job.cancel','Save selection':'label.save','Save box':'label.save','Approve Cyan (raw path)':'label.approve_raw','Approve Orange (leveled path)':'label.approve_leveled','Mark absent':'label.absent','Draft from labeled crops':'description.draft','Check against crops':'description.check','Save tracking settings':'settings.tracking','Save confidence threshold':'settings.confidence','Render with saved corrections':'render.start','Queue Rerendering (no re-analysis)':'render.queue','Re-run analysis':'analysis.rerun','Re-render (no re-analysis)':'render.queue','Discard project':'project.discard','Restore project':'project.restore','Copy corrections to source':'corrections.adopt','Previous tracked frame':'frame.previous_tracked','Next tracked frame':'frame.next_tracked','Previous sampled frame':'frame.previous_sampled','Next sampled frame':'frame.next_sampled','Previous reviewed frame':'frame.previous_reviewed','Next reviewed frame':'frame.next_reviewed','Review descriptions':'description.open','Label subject':'label.open'};
 const safeId=s=>String(s||'').replace(/[^A-Za-z0-9_.-]/g,'').slice(0,80);
 function context(){const c=new URLSearchParams(location.search).get('config')||'';return c.startsWith('.batch/runs/')?{job:safeId(c.split('/')[2])}:{project:safeId(c.replace(/\.json$/,''))}}
 function emit(kind,fields={}){if(!enabled||buffer.length>=200)return;buffer.push({id:crypto.randomUUID(),timestamp:Date.now()/1000,kind,session,workflow,view:page,...context(),...fields});if(buffer.length>=50)flush()}
 function flush(beacon=false){if(!buffer.length)return;const data=JSON.stringify({events:buffer.splice(0,50)});if(beacon)navigator.sendBeacon('/api/lookout/events',new Blob([data],{type:'application/json'}));else originalFetch('/api/lookout/events',{method:'POST',headers:{'Content-Type':'application/json'},body:data}).catch(()=>{})}
 const active=()=>document.visibilityState==='visible'&&document.hasFocus();
 document.addEventListener('mousemove',()=>{if(active()){mouse=true;lastActivity=Date.now()}},{passive:true});
 document.addEventListener('keydown',()=>{if(active()){keyboard=true;lastActivity=Date.now()}},{passive:true});
 document.addEventListener('click',e=>{lastActivity=Date.now();const b=e.target.closest('button,a');if(!b)return;lastAction=crypto.randomUUID();const label=b.textContent.trim();emit('action',{action_id:lastAction,action:b.dataset.lookoutAction||labels[label]||('control.'+safeId(b.id||'other')),section:safeId(b.closest('section')?.id||'main')})},true);
 const edits=new WeakMap();
 document.addEventListener('focusin',e=>{if(e.target.matches('textarea,input:not([type=range]):not([type=checkbox])'))edits.set(e.target,{start:performance.now(),length:e.target.value.length,changed:false})});
 document.addEventListener('input',e=>{const d=edits.get(e.target);if(d)d.changed=true},true);
 document.addEventListener('focusout',e=>{const d=edits.get(e.target);if(!d||!d.changed)return;emit('edit',{action:'field.'+safeId(e.target.id||'other'),duration_ms:performance.now()-d.start,length_delta:e.target.value.length-d.length,saved:false});edits.delete(e.target)});
 document.addEventListener('scroll',()=>{if(Date.now()-lastScroll>5000){lastScroll=Date.now();emit('navigation',{operation:'scroll'})}},{passive:true,capture:true});
 for(const name of ['play','pause','waiting','playing','seeked'])document.addEventListener(name,e=>{if(e.target.tagName!=='VIDEO')return;if(name==='seeked'){clearTimeout(pendingSeek);pendingSeek=setTimeout(()=>emit('playback',{operation:'seeked'}),500)}else emit('playback',{operation:name})},true);
 let drawing=null;
 document.addEventListener('pointerdown',e=>{if(['source','processed'].includes(e.target.id))drawing={start:performance.now(),view:e.target.id}},true);
 document.addEventListener('pointerup',()=>{if(drawing){emit('action',{action:'label.draw',section:drawing.view,duration_ms:performance.now()-drawing.start});drawing=null}},true);
 const seen=new WeakMap();
 const observer=new IntersectionObserver(entries=>{for(const entry of entries){const e=entry.target,key=safeId(e.id||e.dataset.target||'control'),previous=seen.get(e);if(previous===entry.isIntersecting)continue;seen.set(e,entry.isIntersecting);emit('navigation',{operation:'visibility',section:key,control_visible:entry.isIntersecting})}},{threshold:.5});
 setInterval(()=>{document.querySelectorAll('section[id],#saveBox,#approveDescription,#frameNavigation button[data-target]').forEach(e=>{if(!seen.has(e)){seen.set(e,null);observer.observe(e)}})},5000);
 window.addEventListener('error',()=>emit('ui_error',{error_kind:'javascript'}));
 window.addEventListener('unhandledrejection',()=>emit('ui_error',{error_kind:'promise'}));
 window.fetch=async(input,options)=>{
  const url=new URL(typeof input==='string'?input:input.url,location.href),method=options?.method||input?.method||'GET';
  const track=url.origin===location.origin&&url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/api/lookout/')&&method!=='GET';
  const start=performance.now(),action=lastAction;
  try{const response=await originalFetch(input,options);if(track)emit('request',{action_id:action,operation:safeId(url.pathname.replaceAll('/','.')),duration_ms:performance.now()-start,outcome:response.ok?'success':'error',error_kind:response.ok?'none':'http_'+response.status});return response}
  catch(error){if(track)emit('request',{action_id:action,operation:safeId(url.pathname.replaceAll('/','.')),duration_ms:performance.now()-start,outcome:'error',error_kind:'network'});throw error}
 };
 const activity=()=>{const now=Date.now();emit('activity',{mouse,keyboard,visible:document.visibilityState==='visible',focused:document.hasFocus(),active_seconds:active()?Math.max(0,Math.min((now-lastBucket)/1000,30,(60000-(now-lastActivity))/1000)):0});lastBucket=now;mouse=keyboard=false};
 setInterval(()=>{activity();flush()},30000);setInterval(()=>flush(),15000);
 document.addEventListener('visibilitychange',()=>{activity();if(document.hidden)flush(true)});
 window.addEventListener('pagehide',()=>{activity();emit('view',{operation:'leave'});flush(true)});
 async function settings(){try{const r=await originalFetch('/api/lookout/status');const s=await r.json();const first=!enabled;enabled=s.settings.enabled;if(enabled&&first){emit('view',{operation:'enter'});if(performance.getEntriesByType('navigation')[0]?.type==='reload')emit('action',{action:'view.reload'})}if(!enabled)buffer=[]}catch{enabled=false}}
 settings();setInterval(settings,30000);
})();
