// Manual UI smoke test: PLAYWRIGHT_MODULE may point to a bundled Playwright.
// Start a test-only server: python -c "from server import app; app.run(port=5691)"
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  const page = await browser.newPage();
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  const url=process.argv[2] || 'http://127.0.0.1:5691/';
  const response=await page.request.get(url+'api/dashboard');
  assert.equal(response.status(),200);
  const data=await response.json();
  for(const width of [1180,390]) {
    await page.setViewportSize({width,height:1000});
    await page.goto(url);
    await page.waitForFunction(()=>Chart.getChart('rotationRatioChart'));
    const initial=await page.evaluate(()=>({n:Chart.getChart('rotationRatioChart').data.labels.length,instances:Object.keys(Chart.instances).length}));
    await page.getByRole('button',{name:'近1年',exact:true}).click();
    const yearly=await page.evaluate(()=>Chart.getChart('rotationRatioChart').data.labels.length);
    assert(yearly>initial.n);
    await page.getByRole('button',{name:'近3个月',exact:true}).click();
    assert.equal(await page.evaluate(()=>Object.keys(Chart.instances).length),initial.instances);
    assert.equal(await page.evaluate(()=>Chart.getChart('rotationRatioChart').data.labels.length),initial.n);
    const canvas=page.locator('#rotationRatioChart');
    await canvas.scrollIntoViewIfNeeded();
    const point=await page.evaluate(()=>{const c=Chart.getChart('rotationRatioChart');return {x:c.chartArea.left+30,y:c.chartArea.top+30};});
    await canvas.hover({position:point});
    assert(await page.evaluate(()=>Chart.getChart('rotationRatioChart').tooltip.opacity>0));
    assert(await page.locator('#rotationPanel').evaluate(el=>el.scrollWidth<=el.clientWidth));
    const normalized=await page.evaluate(()=>Chart.getChart('rotationPricesChart').data.datasets.map(s=>s.data[0]));
    assert.deepEqual(normalized,[100,100]);
    if(process.env.SMOKE_SCREENSHOTS) await page.locator('#rotationPanel').screenshot({path:process.env.SMOKE_SCREENSHOTS+`/rotation-${width}.png`});
    console.log(JSON.stringify({width,threeMonthPoints:initial.n,yearPoints:yearly,tooltip:true,normalized,chartInstances:initial.instances}));
  }
  // Static-build payload uses the same dashboard schema and page.
  await page.route('**/dashboard.json', route=>route.fulfill({json:data}));
  await page.goto(url);await page.waitForFunction(()=>Chart.getChart('rotationRatioChart'));
  assert.equal(await page.evaluate(()=>IS_STATIC),true);
  await page.evaluate(d=>{render({...d,relative_strength:{available:false,error:'测试：数据暂不可用'}});},data);
  assert(await page.locator('#rotationPanel').innerText().then(t=>t.includes('数据暂不可用')));
  assert.equal(await page.evaluate(()=>!!Chart.getChart('rotationRatioChart')),false);
  await page.evaluate(d=>render(d),data);
  assert.equal(await page.evaluate(()=>!!Chart.getChart('rotationRatioChart')),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: local/static, window switches, tooltip, empty/recovery and no JS errors');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
