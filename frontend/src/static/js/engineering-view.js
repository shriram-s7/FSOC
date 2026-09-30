document.addEventListener('DOMContentLoaded',()=>{
 const holder=document.querySelector('.view-header-row'),button=document.createElement('button');button.className='view-tab-btn';button.textContent='Engineering overlays';button.setAttribute('aria-pressed','false');holder.append(button);
 const note=document.createElement('div');note.className='engineering-note';note.hidden=true;holder.after(note);app.engineering=false;
 app._drawCameraHud=()=>{const t=document.getElementById('camera-feed')._frameState,canvas=document.getElementById('camera-hud-canvas');const status=TrackingOverlay.draw(canvas,t,app.engineering);if(t&&app.engineering)note.textContent=`${status} · score ${t.measurement_score==null?'—':t.measurement_score.toFixed(2)} · ${t.candidate_count??0} candidates · ${Number(t.pipeline_ms||0).toFixed(1)} ms · frame ${t.frame_id}. Cyan: measurement / sensor-centre error; violet: next-step estimate. Box: fixed-size tracking marker.`;};
 button.onclick=()=>{app.engineering=!app.engineering;button.setAttribute('aria-pressed',String(app.engineering));button.classList.toggle('active',app.engineering);note.hidden=!app.engineering;app._drawCameraHud();};
});
