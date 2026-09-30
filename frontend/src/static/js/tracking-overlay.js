/* Sensor-image coordinates only; no simulation truth used for indicators. */
const TrackingOverlay={
 valid(x,y){return Number.isFinite(x)&&Number.isFinite(y);},
 draw(canvas,t,detail=false){
  const c=canvas.getContext('2d');c.clearRect(0,0,canvas.width,canvas.height);if(!t)return;
  c.save();c.scale(canvas.width/640,canvas.height/480);
  const measured=this.valid(t.measured_x,t.measured_y),locked=t.track_state==='LOCKED'&&measured;
  const point=this.valid(t.tracker_x,t.tracker_y)?[t.tracker_x,t.tracker_y]:null;
  const predicting=!measured&&point&&['LOCKED','COASTING','ACQUIRING'].includes(t.track_state);
  const label=measured?'Measured':predicting?'Predicting':'Searching';
  if(point&&(measured||predicting)){c.strokeStyle=locked?'#35ed81':'#ffbd55';c.lineWidth=2;c.setLineDash(predicting?[5,3]:[]);c.strokeRect(point[0]-13,point[1]-13,26,26);c.setLineDash([]);}
  c.font='11px monospace';c.fillStyle=locked?'#35ed81':(predicting||measured)?'#ffbd55':'#ff7979';c.fillText(label,12,20);
  if(detail){
   c.strokeStyle='#ffbd5577';c.lineWidth=1;(t.candidates||[]).forEach(p=>{const r=Math.max(4,p.radius||4);c.strokeRect(p.x-r,p.y-r,r*2,r*2);c.fillStyle='#ffbd55';c.fillText(Number(p.score).toFixed(2),p.x+r+3,p.y);});
   c.strokeStyle='#6ce8ff';c.beginPath();c.moveTo(314,240);c.lineTo(326,240);c.moveTo(320,234);c.lineTo(320,246);c.stroke();
   if(measured){c.fillStyle='#6ce8ff';c.beginPath();c.arc(t.measured_x,t.measured_y,3,0,Math.PI*2);c.fill();}
   if(point){const [x,y]=point,dx=x-320,dy=y-240;c.beginPath();c.moveTo(320,240);c.lineTo(x,y);c.stroke();const a=Math.atan2(dy,dx);c.beginPath();c.moveTo(x,y);c.lineTo(x-7*Math.cos(a-.4),y-7*Math.sin(a-.4));c.moveTo(x,y);c.lineTo(x-7*Math.cos(a+.4),y-7*Math.sin(a+.4));c.stroke();c.fillStyle='#6ce8ff';c.fillText(`dx ${dx.toFixed(1)}  dy ${dy.toFixed(1)}  |e| ${Math.hypot(dx,dy).toFixed(1)} px`,12,465);}
   const p=t.display_prediction;if(p&&this.valid(...p)){const [x,y]=p;c.strokeStyle='#c291ff';c.beginPath();c.moveTo(x,y-6);c.lineTo(x+6,y);c.lineTo(x,y+6);c.lineTo(x-6,y);c.closePath();c.stroke();}
  }c.restore();return label;
 },
 alignment(t,previous={}){
  const measured=t&&this.valid(t.measured_x,t.measured_y)&&t.track_state==='LOCKED',time=t?.sim_time;
  if(!measured||!Number.isFinite(time))return {aligned:false,since:null,label:t?.track_state==='COASTING'?'Detection lost · predicting':'Searching',tone:'red'};
  const dx=t.measured_x-320,dy=t.measured_y-240,error=Math.hypot(dx,dy),within=error<=(previous.aligned?14:10);
  const since=within?(previous.since!=null&&time>=previous.since?previous.since:time):null,aligned=within&&(previous.aligned||time-since>=.5);
  return {dx,dy,error,since,aligned,tone:aligned?'green':'amber',label:aligned?'Aligned ✓':within?'Hold steady…':'Align camera'};
 }
};
