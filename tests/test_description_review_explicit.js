const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{value:'',disabled:false,style:{},replaceChildren(){},append(){},textContent:'',hidden:false});return elements.get(id)}
let calls=[],saved='',statusDescription='cached draft',now=20000;
const sandbox={window:{addEventListener(){}},document:{getElementById:el,createElement:()=>({style:{},append(){}})},location:{hash:'#identity-description'},Date:{now:()=>now},fetch:async(url,opts)=>{calls.push(url);return {ok:true,json:async()=>url==='/api/batch'?{projects:[{project:'p.json',description:saved}]}:{description:url.endsWith('/draft')?'explicit draft':statusDescription,references:[],all_passed:true}}}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/web/description_review.js','utf8'),sandbox);
(async()=>{
 const state={project:'p.json',config:{reference_box:[1,2,3,4]}};
 await sandbox.window.DescriptionReview.update(state);
 assert.equal(el('descriptionText').value,'');assert(!calls.some(u=>u.endsWith('/draft')));
 el('descriptionText').value='Keep this human description';el('descriptionText').oninput();
 now+=11000;statusDescription='different summary after labels changed';await sandbox.window.DescriptionReview.update({...state,corrections:{1:{bbox:[1,2,5,6]}}});
 assert.equal(el('descriptionText').value,'Keep this human description');assert(!calls.some(u=>u.endsWith('/draft')));
 await el('draftDescription').onclick();assert.equal(el('descriptionText').value,'explicit draft');
 console.log('Description remains unchanged on entry and label refresh; explicit drafting still works.');
})().catch(e=>{console.error(e);process.exitCode=1});
