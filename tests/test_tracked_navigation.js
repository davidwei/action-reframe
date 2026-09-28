const fs=require('fs'),vm=require('vm'),assert=require('assert');
const element=()=>({style:{},append(){},textContent:''});
const sandbox={window:{},document:{createElement:element,head:{append(){},appendChild(){}}},console};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('src/web/frame_analysis.js','utf8'),sandbox);
const state={config:{tracking_selection:{confidence_threshold:.5}},meta:{frames:100,samples:[0,10,20,30]},observations:[
{frame:10,bbox:[1,2,3,4],confidence:.6,visibility:'visible'},
{frame:20,bbox:[1,2,3,4],confidence:.9,visibility:'visible'},
{frame:30,bbox:[1,2,3,4],confidence:0,visibility:'visible'},
{frame:40,bbox:[1,2,3,4],confidence:1,visibility:'visible',error:'failed'}],corrections:{20:{bbox:null},50:{bbox:[1,2,3,4]}}};
const nav=sandbox.window.FrameAnalysis.navigationTargets(state,25);
assert.equal(nav.previoustracked,10);assert.equal(nav.nexttracked,50);
assert.equal(sandbox.window.FrameAnalysis.navigationTargets(state,50).nexttracked,null);
assert.equal(sandbox.window.FrameAnalysis.navigationTargets(state,0).previoustracked,null);
console.log('Tracked navigation: confidence, corrections, errors and boundaries passed.');
const overlayState={meta:{width:1920,height:1080,fps:30,analysis_fps:1},tracking_comparison:[{frame:1199,raw_angle:{bbox:[1,2,3,4],confidence:0},leveled:{bbox:[1,2,3,4],confidence:1}},{frame:1229,raw_angle:{bbox:[4,5,6,7]},leveled:{bbox:[4,5,6,7]}}],tracks:Array(1202).fill({bbox:[10,20,30,40]})};
assert.equal(sandbox.window.FrameAnalysis.playbackBoxes(overlayState,1199).length,2);
assert.equal(sandbox.window.FrameAnalysis.playbackBoxes(overlayState,1200).length,0);
assert.equal(sandbox.window.FrameAnalysis.renderedBox(overlayState,1200),null);
console.log('Overlays: exact zero-confidence proposals retained; interpolated/held render boxes suppressed.');
