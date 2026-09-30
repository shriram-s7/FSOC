/* Read-only diagnostics, shared by every view. */
class DiagnosticsDrawer {
  constructor() {
    this.active = 'Pipeline'; this.open = false; this.lines = [];
    this.drawer = document.createElement('aside');
    this.drawer.id = 'diagnostics-drawer'; this.drawer.hidden = true;
    this.drawer.setAttribute('aria-label', 'Diagnostics');
    this.drawer.innerHTML = `<header><h2>Diagnostics</h2><button id="diag-close" aria-label="Close diagnostics">×</button></header>
      <nav role="tablist">${['Pipeline','Model','System','Raw log'].map((x,i)=>`<button role="tab" aria-selected="${i===0}" data-diag-tab="${x}">${x}</button>`).join('')}</nav>
      <div id="diag-content"></div>`;
    document.body.append(this.drawer);
    const launch = document.createElement('button'); launch.id='global-diagnostics';launch.textContent='Diagnostics';launch.title='Diagnostics (Ctrl+D)';
    document.body.append(launch); launch.onclick=()=>this.toggle();
    this.drawer.querySelector('#diag-close').onclick=()=>this.toggle(false);
    this.drawer.querySelectorAll('[data-diag-tab]').forEach(b=>b.onclick=()=>{this.active=b.dataset.diagTab;this.renderShell();this.refresh();});
    window.addEventListener('keydown',e=>{
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='d'){e.preventDefault();e.stopImmediatePropagation();this.toggle();}
      if(e.key==='Escape'&&this.open){e.preventDefault();e.stopImmediatePropagation();this.toggle(false);}
    },true);
  }
  toggle(force) {
    this.open=force===undefined?!this.open:force;
    this.drawer.hidden=!this.open;document.body.classList.toggle('diagnostics-open',this.open);
    clearTimeout(this.timer);
    if(this.open){this.previousFocus=document.activeElement;this.renderShell();this.refresh();this.drawer.querySelector('#diag-close').focus();}
    else this.previousFocus?.focus();
  }
  renderShell() {
    this.drawer.querySelectorAll('[data-diag-tab]').forEach(b=>b.setAttribute('aria-selected',b.dataset.diagTab===this.active));
    const c=this.drawer.querySelector('#diag-content');
    if(this.active==='Pipeline') c.innerHTML=`<section><h3>Frame pipeline (last 120 frames)</h3><canvas id="diag-bars" width="640" height="220" aria-label="Per-frame stage timings"></canvas><div id="diag-legend"></div></section><section><h3>Stage timing (ms)</h3><table><thead><tr><th>Stage</th><th>Mean</th><th>p95</th></tr></thead><tbody id="diag-stages"></tbody></table></section><div class="diag-tiles"><section>Pipeline FPS<strong id="diag-pipeline-fps">—</strong></section><section>End-to-end FPS<strong id="diag-e2e-fps">—</strong></section></div><section><h3>Pipeline time (ms)</h3><canvas id="diag-spark" width="640" height="100"></canvas></section>`;
    else if(this.active==='Raw log') {
      c.innerHTML='<section><label for="diag-filter">Filter backend log</label><input id="diag-filter" placeholder="Filter lines"><button id="diag-copy">Copy</button><label><input id="diag-autoscroll" type="checkbox" checked> Auto-scroll</label><pre id="diag-log"></pre></section>';
      c.querySelector('#diag-filter').oninput=()=>this.renderLog();
      c.querySelector('#diag-copy').onclick=async()=>{try{await navigator.clipboard.writeText(c.querySelector('#diag-log').textContent);}catch{c.querySelector('#diag-copy').textContent='Copy unavailable';}};
    } else c.innerHTML='<section><h3>'+this.active+'</h3><dl id="diag-details"></dl></section>';
  }
  async refresh() {
    if(!this.open)return;
    const tab=this.active;
    try {
      const route=tab==='Pipeline'?'perf':tab==='Raw log'?'backend-log':'diagnostics';
      const data=await API.getDiagnostics(route);
      if(!this.open||tab!==this.active)return;
      if(tab==='Pipeline')this.renderPipeline(data);
      else if(tab==='Raw log'){this.lines=data.lines;this.renderLog();}
      else {
        const values=tab==='Model'?data.model:data.system;
        const dl=this.drawer.querySelector('#diag-details');dl.replaceChildren();
        Object.entries(values).forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k.replaceAll('_',' ');dd.textContent=v==null?'—':Array.isArray(v)?v.join(' × '):typeof v==='boolean'?(v?'Loaded':'Not loaded'):String(v);dl.append(dt,dd);});
      }
    } catch(e) {this.drawer.querySelector('#diag-content').dataset.error='Diagnostics unavailable';}
    finally {clearTimeout(this.timer);if(this.open)this.timer=setTimeout(()=>this.refresh(),tab==='Pipeline'?500:1500);}
  }
  renderLog() {
    const c=this.drawer, filter=c.querySelector('#diag-filter').value.toLowerCase(),el=c.querySelector('#diag-log');
    el.textContent=this.lines.filter(l=>l.toLowerCase().includes(filter)).join('\n')||'—';
    if(c.querySelector('#diag-autoscroll').checked)el.scrollTop=el.scrollHeight;
  }
  renderPipeline(data) {
    const palette=['#2196ff','#38bdf8','#7093b2','#a9c8dd','#b79aff','#f8ba65','#00d6bf','#00e699','#f890b6'];
    const keys=Object.keys(data.stages);
    const legend=this.drawer.querySelector('#diag-legend');
    if(!legend.childElementCount)keys.forEach((key,i)=>{const el=document.createElement('span');el.textContent=key;el.style.borderColor=palette[i];legend.append(el);});
    const format=v=>v==null?'—':v.toFixed(2),tbody=this.drawer.querySelector('#diag-stages');tbody.replaceChildren();
    keys.forEach((key,i)=>{const row=document.createElement('tr');[key,format(data.stages[key].mean),format(data.stages[key].p95)].forEach((v,j)=>{const td=document.createElement('td');td.textContent=v;if(!j){td.style.borderLeft=`3px solid ${palette[i]}`;}row.append(td);});tbody.append(row);});
    this.drawer.querySelector('#diag-pipeline-fps').textContent=format(data.pipeline_fps);
    this.drawer.querySelector('#diag-e2e-fps').textContent=format(data.end_to_end_fps);
    const cv=this.drawer.querySelector('#diag-bars'),ctx=cv.getContext('2d'),frames=data.frames.slice(-6),max=Math.max(1,...frames.map(f=>Object.values(f.stages).reduce((a,b)=>a+(b||0),0)));
    ctx.clearRect(0,0,cv.width,cv.height);ctx.font='14px monospace';
    frames.forEach((f,i)=>{let x=90;const y=i*29+8;ctx.fillStyle='#b2c9dc';ctx.fillText(String(f.frame),6,y+15);keys.forEach((k,j)=>{const w=(f.stages[k]||0)/max*525;ctx.fillStyle=palette[j];ctx.fillRect(x,y,w,21);x+=w;});});
    ctx.fillStyle='#b2c9dc';ctx.fillText('0',90,211);ctx.fillText(max.toFixed(1)+' ms',548,211);
    const spark=this.drawer.querySelector('#diag-spark'),sc=spark.getContext('2d'),series=data.frames.map(f=>f.pipeline_ms);sc.clearRect(0,0,640,100);
    if(series.length){const high=Math.max(1,...series);sc.beginPath();series.forEach((v,i)=>{const x=i/Math.max(1,series.length-1)*640,y=90-v/high*80;i?sc.lineTo(x,y):sc.moveTo(x,y);});sc.strokeStyle='#00f0ff';sc.lineWidth=2;sc.stroke();sc.fillStyle='#b2c9dc';sc.font='12px monospace';sc.fillText(high.toFixed(1),2,12);}
  }
}
document.addEventListener('DOMContentLoaded',()=>{window.fsocDiagnostics=new DiagnosticsDrawer();});
