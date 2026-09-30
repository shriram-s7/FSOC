const CameraLabUI={
  keys:new Set(),mode:'manual',rate:.3,active:false,
  async open(){
    try{
      const state=await API.getState();
      if(state.running){const result=await API.command('stop');if(result.status!=='ready')throw new Error(result.error||'Previous mission could not finish');}
      await API.post('/api/lab/start',{renderer:app.sensorRenderer||'classic'});
    }catch(e){alert(e.message);return;}
    const page=document.getElementById('page-cameralab');
    page.innerHTML=`<div class="page-header"><div><span class="lab-eyebrow">INTERACTIVE CAMERA LAB</span><h2>A fixed beacon. A camera you control.</h2></div><button class="btn" id="lab-exit">Finish lab →</button></div><div class="lab-layout"><section class="card lab-feed"><img id="cameralab-feed" alt="Camera observing a stationary simulated beacon"><div class="lab-feed-note">Pan right → the fixed beacon moves left in the image.</div></section><aside class="card lab-console"><h3>Control ownership</h3><div class="lab-mode-buttons"><button class="btn active" data-lab-mode="manual">Manual</button><button class="btn" data-lab-mode="assist">Track assist</button><button class="btn" data-lab-mode="auto">Auto acquire</button></div><p id="lab-owner" class="muted">User controls camera pointing.</p><div class="lab-pad"><button class="btn" data-key="ArrowUp">↑</button><div><button class="btn" data-key="ArrowLeft">←</button><button class="btn" id="lab-home">Home</button><button class="btn" data-key="ArrowRight">→</button></div><button class="btn" data-key="ArrowDown">↓</button></div><label>Manual rate <select id="lab-rate"><option value=".3">Fine · 0.3°/s</option><option value="2">Coarse · 2°/s</option></select></label><p class="muted">Hold arrows or WASD. Home returns the camera to its initial pointing. Input stops when this window loses focus.</p><div id="lab-values" class="home-system">Waiting for telemetry…</div><canvas id="lab-pointing" width="360" height="240"></canvas><p class="muted">5° pointing envelope · simulated 2D angular viewport. The beacon remains fixed in world coordinates.</p></aside></div>`;
    app.pages.showPage('cameralab');this.active=true;this.mode='manual';this.keys.clear();
    app.labCamera=new CameraFeed(page.querySelector('#cameralab-feed'));app.labCamera.start();
    const feed=page.querySelector('#cameralab-feed'),overlay=document.createElement('canvas');overlay.width=640;overlay.height=480;overlay.className='lab-overlay';feed.after(overlay);
    this.alignment={};this.lastFrameAt=0;
    const badge=document.createElement('div');badge.id='lab-alignment';badge.className='lab-alignment red';badge.setAttribute('role','status');badge.textContent='Searching';page.querySelector('#lab-owner').after(badge);
    const guide=document.createElement('p');guide.id='lab-guidance';guide.className='muted';badge.after(guide);
    feed.onload=()=>{const t=feed._frameState;if(!t)return;this.lastFrameAt=performance.now();TrackingOverlay.draw(overlay,t,false);this.alignment=TrackingOverlay.alignment(t,this.alignment);const a=this.alignment;
      badge.className='lab-alignment '+a.tone;badge.textContent=a.label+(a.error==null?'':` · ${a.error.toFixed(1)} px from centre`);
      const directions=[];if(a.dx>6)directions.push('→ Pan right');if(a.dx< -6)directions.push('← Pan left');if(a.dy>6)directions.push('↓ Tilt down');if(a.dy< -6)directions.push('↑ Tilt up');
      guide.textContent=this.mode==='assist'?(a.error==null?'Waiting for a reliable measurement':directions.join(' · ')||'Hold steady in the centre circle'):this.mode==='auto'?(a.aligned?'Automatic alignment achieved':'Auto aligning…'):'Hold within 10 px for 0.5 s to align. This is alignment feedback, not mission certification.';
      const ctx=overlay.getContext('2d');ctx.strokeStyle=a.aligned?'#35ed81':'#ffbd55';ctx.lineWidth=1;ctx.beginPath();ctx.arc(320,240,10,0,Math.PI*2);ctx.stroke();
    };
    this.staleTimer=setInterval(()=>{if(this.active&&this.lastFrameAt&&performance.now()-this.lastFrameAt>1500){this.alignment={};badge.className='lab-alignment red';badge.textContent='Feed paused · alignment unavailable';guide.textContent='Waiting for fresh camera measurements';}},500);
    this.ws=API.connectStateWS(s=>this.render(s));
    page.querySelectorAll('[data-lab-mode]').forEach(b=>b.onclick=()=>{this.mode=b.dataset.labMode;this.alignment={};this.keys.clear();page.querySelectorAll('[data-lab-mode]').forEach(x=>x.classList.toggle('active',x===b));this.send();});
    page.querySelectorAll('[data-key]').forEach(b=>{b.onpointerdown=e=>{b.setPointerCapture(e.pointerId);this.keys.add(b.dataset.key);this.send();};b.onpointerup=b.onpointercancel=()=>{this.keys.delete(b.dataset.key);this.send();};});
    page.querySelector('#lab-rate').onchange=e=>{this.rate=Number(e.target.value);};
    page.querySelector('#lab-home').onclick=()=>{this.keys.clear();API.post('/api/lab/input',{mode:this.mode,home:true}).catch(e=>alert(e.message));};
    page.querySelector('#lab-exit').onclick=()=>this.exit();
    this.down=e=>{if(!this.active||/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))return;const k=this.key(e.key);if(k){e.preventDefault();this.keys.add(k);this.send();}};
    this.up=e=>{const k=this.key(e.key);if(k){this.keys.delete(k);this.send();}};
    this.blur=()=>{this.keys.clear();this.send();};
    window.addEventListener('keydown',this.down);window.addEventListener('keyup',this.up);window.addEventListener('blur',this.blur);
    this.timer=setInterval(()=>{if(this.keys.size)this.send();},100);
  },
  key(k){return {w:'ArrowUp',a:'ArrowLeft',s:'ArrowDown',d:'ArrowRight',ArrowUp:'ArrowUp',ArrowDown:'ArrowDown',ArrowLeft:'ArrowLeft',ArrowRight:'ArrowRight'}[k];},
  send(){if(!this.active)return;const pan=(this.keys.has('ArrowRight')-this.keys.has('ArrowLeft'))*this.rate,tilt=(this.keys.has('ArrowUp')-this.keys.has('ArrowDown'))*this.rate;API.post('/api/lab/input',{mode:this.mode,pan,tilt}).catch(()=>this.keys.clear());},
  render(s){const l=s.lab_status;if(!l||!this.active)return;document.getElementById('lab-owner').textContent=`${l.owner} · ${l.mode==='assist'?'Tracker measures; user points':l.mode==='auto'?'Controller acquires and centres the beacon':'Manual pointing; tracker cannot move the camera'}`;
    document.getElementById('lab-values').textContent=`Pan ${l.pan.toFixed(2)}°   Tilt ${l.tilt.toFixed(2)}°   ${s.track_state}`;
    const c=document.getElementById('lab-pointing'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle='#284759';ctx.beginPath();ctx.ellipse(180,120,100,100,0,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(60,120);ctx.lineTo(300,120);ctx.moveTo(180,10);ctx.lineTo(180,230);ctx.stroke();ctx.fillStyle='#ffce72';ctx.beginPath();ctx.arc(180,120,5,0,7);ctx.fill();ctx.strokeStyle='#00dbed';ctx.strokeRect(180+l.pan*20-40,120-l.tilt*20-30,80,60);ctx.fillStyle='#b2d4e7';ctx.font='11px monospace';ctx.fillText('Fixed beacon ●   Camera field of view □',35,235);
  },
  cleanup(){clearInterval(this.staleTimer);this.active=false;clearInterval(this.timer);this.ws?.close();this.keys.clear();window.removeEventListener('keydown',this.down);window.removeEventListener('keyup',this.up);window.removeEventListener('blur',this.blur);},
  async exit(){if(!this.active)return;this.keys.clear();this.send();try{await API.post('/api/lab/exit',{});this.cleanup();app.pages.showPage('splash');}catch(e){alert(e.message);}}
};
document.addEventListener('DOMContentLoaded',()=>{app.startCameraLab=()=>CameraLabUI.open();});
