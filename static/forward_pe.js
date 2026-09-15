// Calendar-day interpolation of chart pixels, not historical daily consensus data.
let peData = null, peChart = null, peMonths = 12;

function peAvailable() { return (peData?.charts || []).filter(c => c.digitized?.dates?.length); }
function pePoint(c, date) {
  const s = c?.digitized;
  if (!s) return null;
  const observation = s.observations.find(p=>p.date===date);
  if (observation) return {value:observation.value,low:observation.value,high:observation.value,basis:'图例读数（1位小数）',observed:true};
  // Once collection starts, do not invent values between actual observations.
  const first = s.observations.map(p=>p.date).sort()[0];
  if (first && date >= first) return null;
  const i = s.dates.indexOf(date);
  if (i < 0 || s.values[i] === null) return null;
  return {value:s.values[i], low:s.low[i], high:s.high[i], basis:'历史图片估算·日历日插值', observed:false};
}
function peDatasets(available, dates) {
  return available.flatMap(c=>{
    const color=c.key==='hardware'?'#60a5fa':'#f472b6';
    const s=c.digitized, indices=new Map(s.dates.map((d,i)=>[d,i]));
    const obs=new Map(s.observations.map(p=>[p.date,p.value])), first=[...obs.keys()].sort()[0];
    const points=dates.map(d=>obs.has(d)?{value:obs.get(d),observed:true}:
      d<first&&indices.has(d)&&s.values[indices.get(d)]!==null?{value:s.values[indices.get(d)],observed:false}:null);
    return [{key:c.key,label:c.label,data:points.map(p=>p?.value??null),
      borderColor:color,borderDash:[5,4],borderWidth:1.5,pointRadius:0,pointHoverRadius:4,tension:0,spanGaps:true,
      segment:{borderColor:ctx=>{
        // Connect the collected readings to history, but retain historical occlusion gaps.
        for(let i=ctx.p0DataIndex+1;i<ctx.p1DataIndex;i++) {
          if(dates[i]<first && !points[i]) return 'transparent';
        }
        return color;
      }},
    }].filter(d=>d.data.some(v=>v!==null));
  });
}
function renderForwardPePanel(p) {
  peData = p;
  const available = peAvailable();
  const end = available.map(c=>c.digitized.asof).sort().at(-1) || '';
  return `<section class="panel" id="forwardPePanel">
    <h2>AI 硬件 / 软件 · Forward P/E <span class="flow-status bg-yellow">历史估算 + 图例观测</span></h2>
    <div class="sub">半导体 / 应用软件行业代理 · 未来12个月一致预期经营盈利口径 · 不计入TCI。<br>
      虚线连接早期原图像素估算与后续图例读数，悬浮提示区分两种口径。近期缺少图例的日期不补值，连线仅帮助阅读，不代表中间日期有观测。
      历史估算仍有日期和数值误差；原图遮挡处保留断线。</div>
    <div class="flow-kpis pe-kpis">${(p?.charts || []).map(c=>`<div class="flow-kpi">
      <div class="k">${escapeHtml(c.label)}</div><div class="v">${c.digitized ? c.digitized.latest_legend_pe.toFixed(1)+'×' : '—'}</div>
      <div class="s">图例数据日 ${escapeHtml(c.digitized?.asof || '暂不可用')} · ${escapeHtml(c.industry)}<br>
      ${c.digitized ? `横向约 ${c.digitized.days_per_pixel} 天/像素 · 纵向约 ${c.digitized.pe_per_pixel} 倍/像素<br>` : ''}
      原图抓取 ${escapeHtml(c.fetched_at || '—')}（北京时间）</div>
      ${c.error ? '<div class="c-orange">刷新失败，保留上次成功结果</div>' : ''}
      ${c.data_stale ? '<div class="c-orange">图例日期超过7天未更新</div>' : ''}
    </div>`).join('')}</div>
    ${available.length ? `<div class="rotation-toolbar" role="group" aria-label="估值曲线时间范围">
      ${[[-1,'近期图例'],[3,'3个月'],[12,'1年'],[36,'3年'],[60,'5年'],[0,'全部']].map(([n,label])=>`<button type="button" data-pe-months="${n}" aria-pressed="${peMonths===n}" onclick="setPeWindow(${n})">${label}</button>`).join('')}
      <button type="button" onclick="exportPeCsv()">导出数据 CSV</button></div>
      <div class="rotation-toolbar"><label>开始 <input id="peStart" type="date" onchange="drawForwardPe(true)"></label>
      <label>结束 <input id="peEnd" type="date" value="${end}" onchange="drawForwardPe(true)"></label>
      <span id="peRange" class="meta"></span></div>
      <div class="chart-box"><canvas id="peHistoryChart" role="img" aria-label="AI硬件与软件Forward PE图片估算对比曲线"></canvas></div>
      <div class="rotation-toolbar"><label>查询日期 <input type="date" id="peInspect" value="${end}" onchange="inspectPeDate(this.value)"></label></div>
      <div id="peDateValue" class="sub" aria-live="polite"></div>
      <details><summary>所选范围最近20日明细（无观测留空）</summary><div style="overflow-x:auto"><table><thead><tr><th>日期</th><th>硬件 PE</th><th>软件 PE</th><th>口径</th></tr></thead><tbody id="peRows"></tbody></table></div></details>`
      : '<div class="sub">反推数据暂不可用，仍可查看原图。</div>'}
    <details style="margin-top:12px"><summary>查看两张来源原图与引用</summary>${renderForwardPeSources(p)}</details>
  </section>`;
}
function setPeWindow(months) {
  peMonths = months;
  document.querySelectorAll('[data-pe-months]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.peMonths)===months)));
  drawForwardPe();
}
function peSelectedDates() {
  const start = document.getElementById('peStart').value, end = document.getElementById('peEnd').value;
  return [...new Set(peAvailable().flatMap(c=>c.digitized.dates))].sort().filter(d=>d>=start&&d<=end);
}
function drawForwardPe(custom=false) {
  if (peChart?.canvas) peChart.destroy();
  charts = charts.filter(c=>c!==peChart); peChart = null;
  if (!document.getElementById('peHistoryChart')) return;
  const available = peAvailable();
  if (!custom) {
    const end = available.map(c=>c.digitized.asof).sort().at(-1);
    const cutoff = new Date(end+'T00:00:00Z'); cutoff.setUTCMonth(cutoff.getUTCMonth()-peMonths);
    document.getElementById('peStart').value = peMonths===-1 ? available.flatMap(c=>c.digitized.observations.map(p=>p.date)).sort()[0]
      : peMonths ? cutoff.toISOString().slice(0,10) : available.map(c=>c.digitized.dates[0]).sort()[0];
    document.getElementById('peEnd').value = end;
  } else document.querySelectorAll('[data-pe-months]').forEach(b=>b.setAttribute('aria-pressed','false'));
  const dates = peSelectedDates();
  document.getElementById('peRange').textContent = dates.length ? `${dates[0]} — ${dates.at(-1)} · ${dates.length}个日历日` : '该范围无数据，请检查日期';
  const opts = baseOpts(undefined,undefined);
  opts.scales.y.title = {display:true,text:'Forward P/E（倍）',color:'#9aa3b2'};
  opts.scales.x.ticks.maxTicksLimit = window.innerWidth<600 ? 4 : 10;
  opts.scales.x.ticks.callback = function(v){return this.getLabelForValue(v).slice(2);};
  opts.plugins.tooltip.callbacks = {label:ctx=>{
    const c = available.find(c=>c.key===ctx.dataset.key), point=pePoint(c,ctx.label);
    return point ? `${c.label}: ${point.observed?'':'≈'}${point.value.toFixed(1)}× · ${point.basis}` : `${c.label}: 无数据`;
  }};
  peChart = new Chart(document.getElementById('peHistoryChart'), {type:'line',data:{labels:dates,datasets:peDatasets(available,dates)},options:opts}); charts.push(peChart);
  const byKey = Object.fromEntries((peData.charts||[]).map(c=>[c.key,c]));
  document.getElementById('peRows').innerHTML = dates.slice(-20).reverse().map(d=>{
    const ps=['hardware','software'].map(k=>pePoint(byKey[k],d));
    return `<tr><td>${d}</td>${ps.map(p=>`<td>${p?(p.observed?'':'≈')+p.value.toFixed(1)+'×':'—'}</td>`).join('')}<td>${ps.every(p=>p?.observed)?'图例读数':'含图片估算/缺失'}</td></tr>`;
  }).join('');
  inspectPeDate(document.getElementById('peInspect').value);
}
function inspectPeDate(date) {
  document.getElementById('peDateValue').textContent = peAvailable().map(c=>{
    const p=pePoint(c,date);
    return `${c.label}：${p?(p.observed?'':'≈')+p.value.toFixed(1)+'×（'+p.basis+'）':'该日无可用数据'}`;
  }).join(' ｜ ');
}
function exportPeCsv() {
  const dates=peSelectedDates(), byKey=Object.fromEntries((peData.charts||[]).map(c=>[c.key,c]));
  const rows=[['date','hardware_pe','software_pe','hardware_basis','software_basis','note']];
  for (const d of dates) {
    const ps=['hardware','software'].map(k=>pePoint(byKey[k],d));
    rows.push([d,...ps.map(p=>p?.value??''),...ps.map(p=>p?.basis??'missing'),'Historical pixel estimates; recent legend observations only; source: Yardeni / LSEG / S&P']);
  }
  const csv='\ufeff'+rows.map(row=>row.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));
  const link=document.createElement('a');link.href=url;link.download='forward-pe-history-and-observations.csv';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
