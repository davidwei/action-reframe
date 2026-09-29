const assert=require('assert'),fs=require('fs'),vm=require('vm');
function node(){return {children:[],style:{},textContent:'',append(n){this.children.push(n)},replaceChildren(){this.children=[]}}}
const context={window:{},document:{createElement:node}};
vm.runInNewContext(fs.readFileSync('src/web/tracking_progress.js','utf8'),context);
const render=context.window.TrackingProgressView.render;
const progress={activity:{kind:'verification'},coverage:{stage:'propagating',anchors:1,pending_propagation:2}};
const root=node();
const headings=()=>root.children.find(n=>n.style.cssText?.startsWith('display:flex')).children.map(n=>n.children[0]);
render(root,progress,{running:true});
assert.deepEqual(headings().map(n=>n.textContent.includes('Active')),[false,true,false]);
assert.equal(headings()[1].style.color,'#fbbf24');
render(root,progress,{running:false});assert(headings().every(n=>!n.textContent.includes('Active')));
render(root,{...progress,activity:undefined},{running:true});assert(headings().every(n=>!n.textContent.includes('Active')));
render(root,{...progress,coverage:{...progress.coverage,stage:'complete'}},{running:true});assert(headings().every(n=>!n.textContent.includes('Active')));
console.log('Tracking activity UI checks passed');
