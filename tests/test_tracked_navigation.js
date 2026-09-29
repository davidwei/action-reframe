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
const rejected={frame:10,time:1,bbox:[10,20,30,40],confidence:.95,visibility:'partial',box_verification:{version:7,identity_score:.95,description:{composition:'scene_dominated',visibility:'boundary_cut',viewpoint:'surrounding_camera'},comparison:{localization_support:'ambiguous',localization_reason:'Multiple subjects',exclusion_check:'unclear'},decision:{accepted:false,category:'localization_rejected',reason:'Multiple subjects',threshold:.5}}};
const verifiedState={config:{tracking_selection:{confidence_threshold:.5}},meta:{fps:10,frames:20,width:1920,height:1080},observations:[rejected],tracking_comparison:[{frame:10,raw_angle:rejected,leveled:rejected,selected:rejected}]};
const details=sandbox.window.FrameAnalysis.describe(verifiedState,10);
assert(details.text.includes('localization_rejected'));
assert(details.text.includes('surrounding_camera'));
assert(details.text.includes('95%'));
assert.equal(details.status,'Lost / uncertain observation');
assert.equal(sandbox.window.FrameAnalysis.navigationTargets(verifiedState,0).nexttracked,null);
assert.equal(sandbox.window.FrameAnalysis.playbackBoxes(verifiedState,10).length,2);
console.log('Verification UI: high identity score retained, rejection explained, estimates remain visible.');
const opticalState={meta:{width:1920,height:1080,fps:30,frames:10},optical_motion:{'2':{frame:2,reliable:true,bbox_px:[100,200,300,400],source_frame:1,motion_quality:.9},'3':{frame:3,reliable:false,bbox_px:null,reason:'Lost'}}};
assert.deepEqual(Array.from(sandbox.window.FrameAnalysis.opticalBox(opticalState,2)),[100,200,300,400]);
assert.equal(sandbox.window.FrameAnalysis.opticalBox(opticalState,3),null);
assert.equal(sandbox.window.FrameAnalysis.opticalBox(opticalState,4),null);
assert.equal(sandbox.window.FrameAnalysis.describe(opticalState,2).status,'Optical prediction (unverified)');
const historical={meta:opticalState.meta,observations:[{frame:5,parent_frame:2,propagation_validation:{raw_angle:{analysis_source:'flow_crop_validation',bbox:[100,200,300,400],confidence:0}}}]};
assert.deepEqual(Array.from(sandbox.window.FrameAnalysis.opticalBox(historical,5)),[192,216,576,432]);
assert.equal(sandbox.window.FrameAnalysis.opticalBox(historical,6),null);
console.log('Optical overlay: exact-frame raw pixels, rejected verification retained, failed/neighbor frames suppressed.');

const opticalBoxes=sandbox.window.FrameAnalysis.opticalPlaybackBoxes(opticalState,2);
assert.equal(opticalBoxes[0].path,'optical');
assert.deepEqual(JSON.parse(JSON.stringify(opticalBoxes[0].polygon)),[[100,200],[300,200],[300,400],[100,400]]);
assert.equal(sandbox.window.FrameAnalysis.opticalPlaybackBoxes(opticalState,3).length,0);
assert.equal(sandbox.window.FrameAnalysis.opticalPlaybackBoxes(opticalState,4).length,0);
console.log('Magenta approval/overlay uses exact-frame raw-pixel polygon, including unverified motion.');
