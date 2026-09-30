/* Percentages are measured work completed; unknown work uses an indeterminate ring. */
const ProgressUI={
  panel(title,detail,percent=null){const e=SessionResults.escape,p=percent==null?null:Math.max(0,Math.min(100,percent));return `<div class="work-status" role="status" aria-live="polite"><div class="work-ring ${p==null?'indeterminate':''}" style="--progress:${p||0}%"><span>${p==null?'':Math.floor(p)+'%'}</span></div><div><strong>${e(title)}</strong><p>${e(detail)}</p></div></div>`;},
  async run(title,detail,operation){
    const box=document.createElement('div');box.className='work-backdrop';box.innerHTML=this.panel(title,detail);document.body.append(box);
    const started=performance.now(),timer=setInterval(()=>{const p=box.querySelector('p');p.textContent=detail+` · ${Math.floor((performance.now()-started)/1000)}s elapsed`;},1000);
    try{return await operation();}finally{clearInterval(timer);box.remove();}
  },
  wrap(object,key,title,detail){const original=object[key].bind(object);object[key]=(...args)=>this.run(title,detail,()=>original(...args));}
};
document.addEventListener('DOMContentLoaded',()=>{
  ProgressUI.wrap(app,'startMission','Preparing your mission','Applying configuration and connecting the camera feed');
  ProgressUI.wrap(app,'stopMission','Saving mission evidence','Writing measured results, frame data and the PDF report');
  ProgressUI.wrap(CameraLabUI,'open','Opening Camera Lab','Preparing the stationary beacon and camera controls');
  ProgressUI.wrap(CameraLabUI,'exit','Finishing Camera Lab','Saving this session and restoring mission settings');
  ProgressUI.wrap(VideoPreflight,'prepare','Inspecting your video','Uploading, decoding metadata and preparing preview frames');
  ProgressUI.wrap(VideoPreflight,'attach','Checking ground truth','Validating frame numbers and converting coordinate units');
  ProgressUI.wrap(SessionResults,'open','Loading mission results','Reading saved measurements and plotting the recorded evidence');
  ProgressUI.wrap(ComparisonUI,'load','Loading comparison','Reading the three recordings and matching their source clocks');
});
