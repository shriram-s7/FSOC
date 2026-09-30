document.addEventListener('DOMContentLoaded',()=>{
  const grid=document.getElementById('card-demo').parentElement;grid.classList.add('six-missions');grid.style.setProperty('grid-template-columns','repeat(3,minmax(0,1fr))','important');
  for(const [id,title,description,icon,action] of [
    ['card-lab','CAMERA LAB','Move the camera. Keep the beacon fixed.','◎',()=>CameraLabUI.open()],
    ['card-comparison','MODEL COMPARISON','Compare CV, AI and Hybrid on one scenario.','⤨',()=>ComparisonUI.open()]]){
    const c=document.createElement('div');c.className='mission-card';c.id=id;c.dataset.feature='primary';c.tabIndex=0;c.setAttribute('role','button');c.innerHTML=`<div class="mission-card-icon">${icon}</div><div class="mission-card-title">${title}</div><div class="mission-card-desc">${description}</div><div class="mission-card-arrow">→</div>`;c.onclick=action;c.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();action();}};grid.append(c);
  }
  const choice=document.createElement('div');choice.className='render-choice';choice.innerHTML='<label for="sensor-renderer">Simulation appearance</label><select id="sensor-renderer"><option value="classic">Classic · fallback</option><option value="optical">Optical space · experimental</option></select><small>Optical mode adds a synthetic lens response before detection. Existing models are unchanged. Recorded videos keep their original pixels.</small>';document.querySelector('.home-additions').prepend(choice);
  app.sensorRenderer=localStorage.getItem('fsocRenderer')==='optical'?'optical':'classic';choice.querySelector('select').value=app.sensorRenderer;choice.querySelector('select').onchange=e=>{app.sensorRenderer=e.target.value;app.pages.missionConfig.renderer=app.sensorRenderer;localStorage.setItem('fsocRenderer',app.sensorRenderer);};app.pages.missionConfig.renderer=app.sensorRenderer;
});
