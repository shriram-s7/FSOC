document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-benchmark'),intro=document.createElement('section');intro.className='benchmark-intro';intro.innerHTML='<h3>Five environments. One measured evaluation.</h3><p>The benchmark runs Easy → Moderate → Hard → Severe → Advanced using the selected tracker. Each scenario collects a full minute of evidence before its result appears. Watch the live camera and progress below; failures remain part of the report.</p><label>Run length <select id="bench-duration"><option value="60">Full · 60s per scenario (~5 minutes)</option><option value="15">Preview · 15s per scenario (~75 seconds)</option></select></label> <button class="btn" id="bench-cancel" disabled>Stop after current frame</button><div id="bench-work"></div>';
  page.querySelector('.page-header').after(intro);
  const tbody=document.getElementById('benchmark-table-body');
  function pending(){tbody.innerHTML=['EASY','MODERATE','HARD','SEVERE','ADVANCED'].map(n=>`<tr class="benchmark-queued"><td>${n}</td><td colspan="6">Waiting to run · measurements will appear after this scenario finishes</td><td>QUEUED</td></tr>`).join('');}pending();
  document.getElementById('bench-cancel').onclick=()=>{app.benchmarkCancelled=true;};
  app.runBenchmark=async()=>{
    if(app.benchmarkRunning)return;
    app.benchmarkRunning=true;app.benchmarkCancelled=false;app.benchmarkResults=[];pending();
    const start=document.getElementById('btn-run-benchmark'),cancel=document.getElementById('bench-cancel'),duration=Number(document.getElementById('bench-duration').value),work=document.getElementById('bench-work');start.disabled=true;cancel.disabled=false;
    const presets=['EASY','MOD','HARD','SEV','ADV'],labels=['EASY','MODERATE','HARD','SEVERE','ADVANCED'];
    let missionStarted=false;
    try{
      const active=await API.getState();if(active.running)throw new Error('Finish the active mission before starting the benchmark.');
      app.benchCamera?.stop();app.benchCamera=new CameraFeed(document.getElementById('benchmark-feed'));app.benchCamera.start();
      for(let index=0;index<presets.length;index++){
        if(app.benchmarkCancelled)break;
        work.innerHTML=ProgressUI.panel(`Preparing ${labels[index]}`,'Applying scenario and resetting tracking state');
        await API.setScenario(presets[index]);await API.command('reset');await new Promise(r=>setTimeout(r,900));await API.command('run');missionStarted=true;
        document.getElementById('benchmark-current-name').textContent=labels[index];
        document.querySelectorAll('.pipeline-step').forEach((el,i)=>{el.classList.toggle('done',i<index);el.classList.toggle('current',i===index);});
        const began=performance.now();
        while(performance.now()-began<duration*1000&&!app.benchmarkCancelled){
          if(app.pages.currentPage!=='benchmark'){app.benchmarkCancelled=true;break;}
          const s=await API.getState(),elapsed=Math.min(duration,(performance.now()-began)/1000),pct=(index+elapsed/duration)/5*100;
          work.innerHTML=ProgressUI.panel(`${labels[index]} · scenario ${index+1} of 5`,`${Math.floor(elapsed)} / ${duration}s collected · ${s.track_state} · ${duration===15?'Preview run; limited coverage.':'Saving this scenario when the observation window ends.'}`,pct);
          tbody.rows[index].innerHTML=`<td>${labels[index]}</td><td colspan="6">Collecting measurements · ${Math.floor(elapsed)} / ${duration}s</td><td class="benchmark-running">RUNNING</td>`;
          document.getElementById('benchmark-current-elapsed').textContent=Math.floor(elapsed)+'s';document.getElementById('benchmark-progress').style.width=elapsed/duration*100+'%';
          for(const [id,v] of [['fps',s.fps==null?'—':s.fps.toFixed(1)],['error',s.track_error_px==null?'—':s.track_error_px.toFixed(2)+' px'],['lock',s.lock_rate==null?'—':(s.lock_rate*100).toFixed(1)+'%'],['state',s.track_state]])document.getElementById('bench-metric-'+id).textContent=v;
          await new Promise(r=>setTimeout(r,500));
        }
        work.innerHTML=ProgressUI.panel('Saving '+labels[index],'Writing the scenario report and measured result');
        const done=await API.command('stop');missionStarted=false;if(done.status!=='ready'||!done.session_id)throw new Error(done.error||'No completed session');
        const record=await API.request('/api/sessions/'+done.session_id),s=record.summary,f=SessionResults.value;
        tbody.rows[index].innerHTML=`<td>${labels[index]}</td><td>${record.configuration.runtime_disturbances?.low_light?'low light':record.configuration.runtime_disturbances?.atmosphere||'—'}</td><td>${record.configuration.motion?.type||'—'}</td><td>${f(s.acquisition_time_s,'s')}</td><td>${f(s.mean_track_error_px,'px')}</td><td>${f(s.target_loss_pct,'%')}</td><td>${f(s.mean_fps)}</td><td><button class="btn">${app.benchmarkCancelled?'STOPPED · ':duration===15?'PREVIEW · ':''}${record.requirements.overall}</button></td>`;
        tbody.rows[index].querySelector('button').onclick=()=>SessionResults.open(done.session_id);app.benchmarkResults.push(record);
      }
      if(!app.benchmarkCancelled)document.querySelectorAll('.pipeline-step').forEach(el=>{el.classList.remove('current');el.classList.add('done');});
      work.innerHTML=ProgressUI.panel(app.benchmarkCancelled?'Benchmark stopped':'Benchmark complete',`${app.benchmarkResults.length} saved scenario reports. Select a result to inspect its evidence.`,app.benchmarkCancelled?null:100);
    }catch(e){work.innerHTML=ProgressUI.panel('Benchmark interrupted',e.message);}
    finally{if(missionStarted)await API.command('stop').catch(()=>{});app.benchCamera?.stop();app.benchCamera=null;app.benchmarkRunning=false;start.disabled=false;cancel.disabled=true;}
  };
});
