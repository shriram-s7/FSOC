document.addEventListener('DOMContentLoaded',()=>{
  ['builder','brief'].forEach((id,index)=>{
    const p=document.getElementById('page-'+id),flow=document.createElement('div');flow.className='mission-steps';flow.innerHTML=['Build','Brief','Execute','Results'].map((s,i)=>`<span class="${i===index?'current':''}">${i+1} · ${s}</span>`).join('<b>—</b>');p.querySelector('.page-header').after(flow);
  });
  const brief=document.getElementById('page-brief'),edit=document.createElement('button');edit.className='btn';edit.textContent='← Edit mission';edit.onclick=()=>app.pages.showPage('builder');brief.querySelector('.page-header').append(edit);
  const populate=app._populateBrief.bind(app);app._populateBrief=async()=>{await populate();try{
    const data=await API.post('/api/mission/preview',app.pages.missionConfig),svg=document.getElementById('mission-preview-svg');
    svg.setAttribute('viewBox','0 0 440 330');const points=data.points.map(p=>`${20+p.x/5},${20+p.y/7}`).join(' '),first=data.points[0],last=data.points.at(-1);
    svg.innerHTML=`<rect width="440" height="330" fill="#04101b"/><defs><pattern id="preview-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#163042" stroke-width=".5"/></pattern></defs><rect width="440" height="330" fill="url(#preview-grid)"/><rect x="156" y="129" width="128" height="69" stroke="#00d5ea" fill="#00aabb08"/><polyline points="${points}" stroke="#94eff7" stroke-width="1.5" stroke-dasharray="4 3" fill="none"/><circle cx="${20+first.x/5}" cy="${20+first.y/7}" r="5" fill="#27e9ac"/><circle cx="${20+last.x/5}" cy="${20+last.y/7}" r="5" fill="#ff7385"/><text x="16" y="320" fill="#9cc4d9" font-size="11">Planned trajectory · 20 seconds · initial camera FOV</text>`;
  }catch(e){document.getElementById('mission-preview-svg').innerHTML='<text x="15" y="30" fill="#ffce72">Preview unavailable</text>';}};
  const update=app.updateMissionControl.bind(app);app.updateMissionControl=s=>{update(s);if(s.video_done&&s.finalisation==='ready'&&s.finished_session_id&&app.pages.currentPage==='control'&&app._openedVideoResult!==s.finished_session_id){app._openedVideoResult=s.finished_session_id;app.stopMission();}};
});
