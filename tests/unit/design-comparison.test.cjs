const {test}=require('node:test');
const assert=require('node:assert/strict');
const {ComparisonPanelState,clampPan}=require('../../management/static/management/js/design_comparison.js');
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
