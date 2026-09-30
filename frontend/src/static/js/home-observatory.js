/* Presentation only: mission actions and sensor rendering remain independent. */
document.addEventListener('DOMContentLoaded',()=>{
 const home=document.getElementById('page-splash'),hero=home.children[2];
 hero.classList.add('observatory-hero');
 hero.querySelector('.six-missions').style.removeProperty('grid-template-columns');
 hero.children[0].classList.add('old-home-emblem');
 const title=hero.querySelector('h1');
 const eyebrow=document.createElement('div');eyebrow.className='observatory-eyebrow';eyebrow.textContent='OPTICAL TRACKING / MISSION WORKSPACE';title.before(eyebrow);
 title.innerHTML='Precision in motion<span class="hero-period">.</span>';
 title.nextElementSibling.textContent='Acquire the signal. Align the camera. Explore autonomous optical tracking.';
 title.nextElementSibling.nextElementSibling.classList.add('mission-picker-label');
 title.nextElementSibling.nextElementSibling.textContent='CHOOSE YOUR MISSION';
 const art=document.createElement('aside');art.className='observatory-art';art.setAttribute('aria-hidden','true');
 art.innerHTML=`<svg viewBox="0 0 800 520" fill="none"><defs><radialGradient id="planetLight" cx=".32" cy=".05" r=".85"><stop stop-color="#408fba"/><stop offset=".18" stop-color="#15374d"/><stop offset=".6" stop-color="#071420"/><stop offset="1" stop-color="#030910"/></radialGradient><linearGradient id="signalLight"><stop stop-color="#64efde" stop-opacity="0"/><stop offset="1" stop-color="#64efde"/></linearGradient></defs><circle cx="550" cy="480" r="270" fill="url(#planetLight)" stroke="#79d8ec" stroke-opacity=".4"/><ellipse cx="500" cy="280" rx="330" ry="125" transform="rotate(-28 500 280)" stroke="#6fbed1" stroke-opacity=".24"/><ellipse cx="500" cy="280" rx="330" ry="125" transform="rotate(-28 500 280)" stroke="#6fbed1" stroke-opacity=".16" stroke-dasharray="2 16" stroke-width="8"/><path d="M140 382L563 152" stroke="url(#signalLight)"/><circle cx="563" cy="152" r="34" stroke="#75f1dd" stroke-opacity=".16"/><circle cx="563" cy="152" r="19" stroke="#75f1dd" stroke-opacity=".45"/><circle cx="563" cy="152" r="4" fill="#b9fff1"/><path d="M563 105v20m0 54v20m-47-47h20m54 0h20" stroke="#75f1dd" stroke-opacity=".7"/><g fill="#cde5f4"><circle cx="155" cy="110" r="1.5"/><circle cx="360" cy="77" r="1"/><circle cx="699" cy="90" r="1.8"/><circle cx="730" cy="265" r="1"/><circle cx="271" cy="215" r="1"/></g></svg>`;
 home.prepend(art);
 const cards=[
 ['demo','01','START HERE','Quick demo','See acquisition and tracking in action.','Launch demonstration','#6ee7d2','<path d="m10 7 9 5-9 5Z"/><circle cx="12" cy="12" r="10"/>'],
 ['custom','02','CONFIGURE','Custom mission','Shape the motion, environment and challenge.','Build a scenario','#83b9ff','<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>'],
 ['benchmark','03','EVALUATE','Benchmark','Run a suite of automated tracking tests.','Open test suite','#ebc07b','<path d="M4 20V12h4v8m4 0V7h4v13m4 0V3h3v17M2 21h22"/>'],
 ['video','04','REPLAY','Load video','Bring your recording into the tracking pipeline.','Choose a recording','#b3a0ff','<rect x="3" y="4" width="20" height="16" rx="3"/><path d="m10 8 7 4-7 4Z"/>'],
 ['lab','05','INTERACTIVE','Camera lab','Take the controls. Find and centre the beacon.','Enter camera lab','#65d4eb','<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M12 6v12M6 12h12"/><circle cx="12" cy="12" r="4"/>'],
 ['comparison','06','COMPARE','Model comparison','Watch CV, AI and Hybrid tackle one scenario.','Compare trackers','#f49eab','<path d="M3 5h6v14H3zM10 9h6v10h-6zM17 3h6v16h-6z"/>']
 ];
 cards.forEach(([id,n,tag,label,desc,action,color,icon])=>{
  const card=document.getElementById('card-'+id);card.style.setProperty('--card-accent',color);
  card.innerHTML=`<div class="mission-card-top"><span class="mission-card-icon"><svg viewBox="0 0 26 26" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg></span><span class="mission-card-category">${tag}</span><span class="mission-card-number">${n}</span></div><div class="mission-card-title">${label}</div><div class="mission-card-desc">${desc}</div><div class="mission-card-footer"><span>${action}</span><span class="mission-card-arrow" aria-hidden="true">↗</span></div>`;
  card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',label);card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();card.click();}};
 });
});

