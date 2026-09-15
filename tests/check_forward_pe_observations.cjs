// No browser/network needed: verify display, tooltip lookup and CSV data semantics.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const dates=['2026-09-03','2026-09-04','2026-09-05','2026-09-08','2026-09-10','2026-09-11'];
// Deliberately use an old cache with bogus recent pixel estimates: frontend must ignore them.
const chart={key:'hardware',label:'半导体',digitized:{dates,values:[16,16.2,15.8,15.7,15.1,14.9],low:[15,15,15,15,15,15],high:[17,17,17,17,17,17],
  observations:[{date:'2026-09-04',value:16.7},{date:'2026-09-08',value:15.9},{date:'2026-09-10',value:15.5},{date:'2026-09-11',value:15.6}]}};
let blob;
const context={chart,dates,Blob,URL:{createObjectURL:b=>{blob=b;return 'blob:test'},revokeObjectURL:()=>{}},setTimeout:f=>f(),
  document:{getElementById:id=>({value:id==='peStart'?'2026-09-03':'2026-09-11'}),createElement:()=>({click:()=>{}})}};
vm.createContext(context);vm.runInContext(fs.readFileSync('static/forward_pe.js','utf8'),context);
assert.equal(vm.runInContext("pePoint(chart,'2026-09-05')",context),null);
assert.equal(vm.runInContext("pePoint(chart,'2026-09-04').value",context),16.7);
const sets=vm.runInContext('peDatasets([chart],dates)',context);
assert.equal(sets.length,2);assert.deepEqual(Array.from(sets[0].data),[16,null,null,null,null,null]);
assert.deepEqual(Array.from(sets[1].data),[null,16.7,null,15.9,15.5,15.6]);
assert.equal(sets[0].spanGaps,false);assert.equal(sets[1].pointRadius,3);
vm.runInContext('peData={charts:[chart]}; exportPeCsv()',context);
blob.text().then(csv=>{
  assert(csv.includes('"2026-09-05","","","missing"'));
  assert(csv.includes('"2026-09-11","15.6"'));
  console.log('PASS: observed reversal preserved, missing days blank, separate datasets and CSV');
}).catch(e=>{console.error(e);process.exitCode=1;});
