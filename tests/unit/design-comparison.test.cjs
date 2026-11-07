const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ComparisonPanelState,clampPan,comparisonSelection}=require('../../management/static/management/js/design_comparison.js');
test('every entry selects the server-resolved latest upload and preserves the clicked reference',()=>{
 const data={references:[{id:1,type:'image'},{id:2,type:'pdf'}],uploads:[{id:9},{id:3}],latest_upload_id:3};
 assert.deepEqual(comparisonSelection(data,'2'),{reference:1,upload:1,side:'reference'});
 assert.deepEqual(comparisonSelection(data,1),{reference:0,upload:1,side:'reference'});
 assert.deepEqual(comparisonSelection(data,9),{reference:0,upload:1,side:'upload'});
 data.uploads.reverse();
 assert.deepEqual(comparisonSelection(data,9),{reference:0,upload:0,side:'upload'});
});
test('nonempty designer sets require a valid authorized latest upload',()=>{
 assert.throws(()=>comparisonSelection({references:[{id:2}],uploads:[{id:9}],latest_upload_id:99},2),/Invalid comparison/);
 assert.throws(()=>comparisonSelection({references:[{id:2}],uploads:[{id:9}]},2),/Invalid comparison/);
});
test('reference entry permits an empty designer set but rejects missing or invalid anchors',()=>{
 assert.deepEqual(comparisonSelection({references:[{id:2}],uploads:[]},2),{reference:0,upload:-1,side:'reference'});
 assert.throws(()=>comparisonSelection({references:[],uploads:[{id:1}]},2),/Invalid comparison/);
 assert.throws(()=>comparisonSelection({references:null,uploads:[]},2),/Invalid comparison/);
});
test('reference and upload navigation remain independent, including wraparound',()=>{
 const left=new ComparisonPanelState([{id:1},{id:2}]),right=new ComparisonPanelState([{id:3},{id:4},{id:5}]);
 left.select(0);right.select(1);left.move(1);assert.equal(left.current().id,2);assert.equal(right.current().id,4);
 left.move(1);assert.equal(left.current().id,1);right.move(-2);assert.equal(right.current().id,5);assert.equal(left.current().id,1);
});
test('PDF pages never change selected file or another panel page and zoom',()=>{
 const left=new ComparisonPanelState([{id:1},{id:2}]),right=new ComparisonPanelState([{id:3}]);left.select(0);right.select(0);
 left.changePage(1,3);right.changePage(2,5);left.zoom(2,true);assert.equal(left.page,2);assert.equal(right.page,3);assert.equal(right.scale,1);
 left.changePage(100,3);assert.equal(left.page,3);assert.equal(left.current().id,1);left.move(1);assert.equal(left.page,1);assert.equal(left.scale,1);assert.equal(right.page,3);
});
test('fit resets only pan/zoom while retaining file and PDF page',()=>{
 const p=new ComparisonPanelState([{id:1},{id:2}]);p.select(1);p.changePage(2,5);p.zoom(3,true);p.x=100;p.y=20;p.fit();
 assert.deepEqual([p.index,p.page,p.scale,p.x,p.y],[1,3,1,0,0]);
});
test('zoom and pan are bounded and empty sets never select unrelated files',()=>{
 const p=new ComparisonPanelState();assert.equal(p.select(10),null);assert.equal(p.move(-1),null);
 p.zoom(100);assert.equal(p.scale,8);p.zoom(0.0001);assert.equal(p.scale,1);p.zoom(0.0001,true);assert.equal(p.scale,0.25);
 assert.equal(clampPan(300,800,400),200);assert.equal(clampPan(-300,800,400),-200);assert.equal(clampPan(30,200,400),0);
});
