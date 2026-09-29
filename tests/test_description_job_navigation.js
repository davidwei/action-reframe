const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function node(){return {value:'',textContent:'',style:{},disabled:false,hidden:false,append(){},replaceChildren(){}}}
let now=Date.now();class Clock extends Date{static now(){return now}}
const jobs={a:{status:'running',action:'check',started:now/1000},b:null};
const sandbox={window:{addEventListener(){}},document:{getElementById(id){if(!elements.has(id))elements.set(id,node());return elements.get(id)},createElement:node},Date:Clock,console,
 fetch:async(url,options)=>{
  const body=options?JSON.parse(options.body):{};
  const value=url==='/api/batch'?{projects:[{project:'a',description:'Boat'},{project:'b',description:'Boat'}]}:
   url.endsWith('description-status')?{job:jobs[body.project],description:'Boat',references:[{frame:0,time:0,crop_path:'crop.png',expected_present:true}]}:{revisions:[]};
  return {ok:true,json:async()=>value};
 }};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/web/description_review.js','utf8'),sandbox);
(async()=>{
 const state=project=>({project,config:{reference_box:[0,0,10,10]}});
 await sandbox.window.DescriptionReview.update(state('a'));
 assert.equal(elements.get('checkDescription').disabled,true);
 assert(elements.get('descriptionStatus').textContent.includes('running'));
 await sandbox.window.DescriptionReview.update(state('b'));
 assert.equal(elements.get('checkDescription').disabled,false);
 await sandbox.window.DescriptionReview.update(state('a'));
 assert.equal(elements.get('checkDescription').disabled,true);
 jobs.a={status:'succeeded',action:'check'};now+=11000;
 await sandbox.window.DescriptionReview.update(state('a'));
 assert.equal(elements.get('checkDescription').disabled,false);
 console.log('Navigation preserves per-project running state and polling re-enables completed checks.');
})().catch(e=>{console.error(e);process.exitCode=1});
