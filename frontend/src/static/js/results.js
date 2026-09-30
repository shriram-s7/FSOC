/* Session-centred archive and results; never infers measurements from filenames. */
const SessionResults = {
  escape(v) { const e=document.createElement('span');e.textContent=String(v??'');return e.innerHTML; },
  value(v, unit='') { return v==null||v===''||!Number.isFinite(Number(v)) ? '—' : `${Number(v).toFixed(2).replace(/\.00$/,'')} ${unit}`.trim(); },
  async list() {
    const page=document.getElementById('page-reports');
    page.innerHTML='<div class="page-header"><h2>Mission archive</h2><button class="btn" onclick="app.pages.showPage(\'splash\')">Home</button></div><div class="session-list">Loading saved sessions…</div>';
    try {
      const records=await API.request('/api/sessions');
      page.querySelector('.session-list').innerHTML=records.length ? records.map(r=>`<button class="session-row" data-session="${this.escape(r.session_id)}"><span><strong>${this.escape(r.session_id)}</strong><small>${this.escape(r.summary.detector_mode)} · ${this.escape(r.source)} · ${this.value(r.summary.simulation_duration_sec??r.summary.duration_sec,'s')}</small></span><span class="outcome ${r.requirements.overall}">${r.requirements.overall.replaceAll('_',' ')}</span><span>RMSE ${this.value(r.summary.rmse_px,'px')} →</span></button>`).join(''):'No completed sessions yet. Finish a mission to save its results.';
      page.querySelectorAll('[data-session]').forEach(b=>b.onclick=()=>this.open(b.dataset.session));
    } catch(e) { page.querySelector('.session-list').textContent=e.message; }
  },
  async open(id) {
    const token=this.token=Symbol();
    let page=document.getElementById('page-results');
    if(!page){page=document.createElement('section');page.id='page-results';page.className='page';document.querySelector('main').append(page);}
    app.pages.showPage('results');page.innerHTML='<div class="page-header"><h2>Loading mission results…</h2></div>';
    if(this.chart){this.chart.destroy();this.chart=null;}
    try {
      const [r,frames]=await Promise.all([API.request('/api/sessions/'+encodeURIComponent(id)),API.request('/api/sessions/'+encodeURIComponent(id)+'/frames')]);
      if(this.token!==token)return;
      this.current=r;const s=r.summary, e=this.escape, f=this.value;
      page.innerHTML=`<div class="page-header"><h2>Mission results</h2><button class="btn" id="result-archive">All sessions</button></div>
        <div class="result-banner"><div><div class="result-outcome ${r.requirements.overall}">${r.requirements.overall.replaceAll('_',' ')}</div><p>${e(id)}</p></div><div><h3>Measured mission performance</h3><p>${e(r.requirements.policy)}</p><div class="result-actions">${Object.keys(r.artifacts).filter(k=>k!=='centroid').map(k=>`<a class="btn ${k==='pdf'?'btn-primary':''}" href="${API.BASE}/api/sessions/${encodeURIComponent(id)}/artifacts/${k}" target="_blank">${k==='pdf'?'Export PDF':k==='frames'?'Frame CSV':'Summary CSV'}</a>`).join('')}</div></div></div>
        <div class="result-grid"><section class="card"><h3>Configured PS checks</h3><p class="muted">${e(r.requirements.provenance)}</p><table class="data-table"><thead><tr><th>Requirement</th><th>Limit</th><th>Achieved</th><th>Status</th></tr></thead><tbody>${r.requirements.rows.map(row=>`<tr><td>${e(row.label)}</td><td>${e(row.operator)} ${row.limit} ${e(row.unit)}</td><td>${f(row.value,row.unit)}</td><td><span class="outcome ${row.status}">${row.status.replaceAll('_',' ')}</span><small>${e(row.reason)}</small></td></tr>`).join('')}</tbody></table></section>
        <section class="card"><h3>Configuration snapshot</h3><div class="config-grid">${Object.entries(r.configuration||{}).filter(([k])=>['motion','target','camera','detection','rendering'].includes(k)).map(([k,v])=>`<div><h4>${e(k)}</h4>${Object.entries(v).filter(([,v])=>typeof v!=='object').map(([a,b])=>`<p><span>${e(a.replaceAll('_',' '))}</span><strong>${e(b)}</strong></p>`).join('')}</div>`).join('')||'<p>Configuration was not saved for this legacy session.</p>'}</div></section></div>
        <section class="card result-analysis"><div class="page-header"><h3>Mission analysis · source time</h3><select id="result-series"><option value="error">${s.mode==='video'?'Centroid error vs GT':'Pointing error'} (px)</option><option value="confidence">Confidence</option><option value="fps">End-to-end FPS</option></select></div><div class="result-chart"><canvas id="session-chart"></canvas></div><p class="muted">Gaps are unavailable measurements. Error is shown only for locked frames. Confidence is a tracker score, not measured accuracy.</p></section>
        <div class="result-grid"><section class="card"><h3>Detailed measurements</h3><table class="data-table"><tbody>${[['Source duration',s.simulation_duration_sec,'s'],['Wall duration',s.duration_sec,'s'],['Total frames',s.total_frames,''],['RMSE',s.rmse_px,'px'],['Maximum error',s.max_track_error_px,'px'],['Centroid RMSE vs GT',s.centroid_rmse_px,'px'],['Correct lock / all frames',s.correct_lock_pct,'%'],['Correct lock / visible frames',s.correct_lock_visible_pct,'%'],['Tracker-state lock',s.lock_rate_pct,'%'],['Out of view',s.beacon_out_of_fov_pct,'%'],['Wrong-lock events',s.wrong_lock_events,''],['End-to-end rate',s.mean_fps,'FPS'],['Pipeline-only rate',s.processing_fps,'FPS']].map(([a,b,c])=>`<tr><td>${a}</td><td>${f(b,c)}</td></tr>`).join('')}</tbody></table></section><section class="card"><h3>Recorded changes</h3>${r.events.length?r.events.map(ev=>`<p>${f(ev.time_s,'s')} · ${e(ev.type)} ${e(JSON.stringify(ev.details||{}))}</p>`).join(''):'<p>No saved mid-run changes.</p>'}<h3>Replay</h3><p class="muted">A persistent recording is not available for this session. Frame measurements remain available in the CSV export.</p></section></div>`;
      page.querySelector('#result-archive').onclick=()=>{app.pages.showPage('reports');this.list();};
      const draw=()=>{
        const mode=page.querySelector('#result-series').value;
        if(this.chart)this.chart.destroy();
        const data=frames.map(row=>{
          const x=Number(row.sim_time||row.timestamp_s||0);let y=null;
          if(mode==='error'&&row.state==='LOCKED'&&!row.plot_gap){
            if(s.mode==='video') { if(['tracker_x','tracker_y','gt_x','gt_y'].every(k=>row[k]!=null&&row[k]!==''))y=Math.hypot(Number(row.tracker_x)-Number(row.gt_x),Number(row.tracker_y)-Number(row.gt_y)); }
            else if(row.track_error_px!==''&&row.track_error_px!=null)y=Number(row.track_error_px);
          }else if(mode!=='error'&&row[mode]!=null&&row[mode]!=='')y=Number(row[mode]);
          return {x,y};
        });
        this.chart=new Chart(page.querySelector('#session-chart'),{type:'line',data:{datasets:[{label:mode,data,borderColor:'#00d9ed',borderWidth:1.5,pointRadius:0,spanGaps:false}]},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{type:'linear',title:{display:true,text:'Source time (s)'}},y:{beginAtZero:true}},plugins:{legend:{display:false}}}});
      };page.querySelector('#result-series').onchange=draw;draw();
    }catch(error){if(this.token===token){page.innerHTML='<div class="card"><h2>Results unavailable</h2><p></p><button class="btn" onclick="app.pages.showPage(\'reports\');app.refreshReportsList()">Back to archive</button></div>';page.querySelector('p').textContent=error.message;}}
  }
};
