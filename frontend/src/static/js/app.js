/* FSOC-PAT — main application controller. */

const STATE_COLORS = {
  LOCKED: '#00e699',
  ACQUIRING: '#ff8800',
  SEARCHING: '#ba9aff',
  COASTING: '#38bdf8',
  LOST: '#ff7787'
};

const STATE_ICONS = {
  LOCKED: '✅',
  ACQUIRING: '⏳',
  SEARCHING: '\u{1F50D}',
  COASTING: '\u{1F6F0}',
  LOST: '❌'
};

const FLOW_ORDER = ['SEARCHING', 'ACQUIRING', 'LOCKED', 'TRACK', 'COASTING'];

const CAM_STATUS_MAP = {
  LOCKED: 'FOLLOWING',
  COASTING: 'FOLLOWING',
  ACQUIRING: 'ACQUIRING',
  SEARCHING: 'SEARCHING',
  LOST: 'SEARCHING'
};

function hexToRgba(hex, alpha) {
  const n = parseInt(hex.replace('#', ''), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function fmtElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, '0');
  const s = String(total % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function fmtElapsedWithTenths(ms) {
  const totalSec = Math.max(0, ms / 1000);
  const m = String(Math.floor(totalSec / 60)).padStart(2, '0');
  const s = String(Math.floor(totalSec % 60)).padStart(2, '0');
  const t = Math.floor((totalSec % 1) * 10);
  return `${m}:${s}.${t}`;
}

function fmtDurationSec(sec) {
  if (sec == null || isNaN(sec)) return '--:--';
  const s = Math.max(0, Number(sec));
  const m = String(Math.floor(s / 60)).padStart(2, '0');
  const sc = String(Math.floor(s % 60)).padStart(2, '0');
  const t = Math.floor((s % 1) * 10);
  return `${m}:${sc}.${t}`;
}

function drawSparkline(canvas, data, strokeColor, fillColor) {
  if (!canvas || !data || data.length < 2) return;
  const now = performance.now();
  if (now - (canvas._lastPaint || 0) < 250) return;
  canvas._lastPaint = now;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  let min = Math.min(...data);
  let max = Math.max(...data);
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  
  ctx.beginPath();
  const step = w / (data.length - 1);
  data.forEach((val, i) => {
    const x = i * step;
    const y = h - ((val - min) / range) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = strokeColor || '#00d4ff';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // fill under curve
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.fillStyle = fillColor || 'rgba(0, 212, 255, 0.15)';
  ctx.fill();
}

function initStarfield() {
  const canvas = document.getElementById('splash-stars');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const stars = Array.from({ length: 150 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    r: Math.random() * 1.5 + 0.3,
    o: Math.random() * 0.7 + 0.1,
    speed: Math.random() * 0.3 + 0.05
  }));
  function draw() {
    if (!document.getElementById('page-splash').classList.contains('active')) { requestAnimationFrame(draw); return; }
    ctx.fillStyle = '#080c14';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    stars.forEach(s => {
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${s.o})`;
      ctx.fill();
      s.o += (Math.random() - 0.5) * 0.02;
      s.o = Math.max(0.05, Math.min(0.9, s.o));
    });
    requestAnimationFrame(draw);
  }
  draw();
}

class FSocApp {
  constructor() {
    this.pages = new PageManager();
    this.camera = null;
    this.worldView = null;
    this.stateWS = null;
    this.currentState = {};
    this.missionStartTime = null;
    this.errorHistory = [];
    this.chart = null;
    this.isPaused = false;
    this.elapsedTimer = null;
    this.clockTimer = null;

    this.benchmarkRunning = false;
    this.benchmarkResults = [];
    this.selectedReport = null;

    this.sparkData = {
      trackErr: [],
      acqTime: [],
      targetLoss: [],
      reacqTime: [],
      fps: [],
      lockRet: []
    };

    this.eventCount = 0;
    this._lastTrackState = null;
    this._lastAtmosphere = null;
    this._activeView = 'camera';
  }

  init() {
    initStarfield();

    this.setupSplash();
    this.setupHomeButton();
    this.setupBuilder();
    this.setupBrief();
    this.setupControl();
    this.setupCameraLab();
    this.setupBenchmark();
    this.setupReports();

    this.worldView = new WorldView(document.getElementById('world-view'));

    // Digital real-time clock
    this._startClock();

    // Global keyboard shortcuts
    this._setupShortcuts();

    this.pages.showPage('splash');
  }

  _startClock() {
    const clockEl = document.getElementById('topbar-clock');
    const update = () => {
      if (clockEl) {
        const d = new Date();
        clockEl.textContent = d.toTimeString().split(' ')[0];
      }
    };
    update();
    this.clockTimer = setInterval(update, 1000);
  }

  _setupShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (this.pages.currentPage !== 'control') return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.code === 'Space') {
        e.preventDefault();
        this.togglePause();
      } else if (e.code === 'Escape') {
        e.preventDefault();
        this.stopMission();
      } else if (e.key === 'v' || e.key === 'V') {
        e.preventDefault();
        this._switchView(this._activeView === 'camera' ? 'world' : 'camera');
      } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        this.takeScreenshot();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'd' || e.key === 'D')) {
        e.preventDefault();
        this.showDiagnostics();
      }
    });
  }

  // ==================== SPLASH ====================
  setupSplash() {
    document.getElementById('video-file-input').addEventListener('change', async (e) => {
      // One MP4, plus optionally its ground-truth CSV picked alongside it.
      const files = Array.from(e.target.files);
      const file = files.find(f => !f.name.toLowerCase().endsWith('.csv'));
      const gtFile = files.find(f => f.name.toLowerCase().endsWith('.csv'));
      if (!file) return;
      try {
        const res = await API.loadVideo(file, gtFile);
        console.log('Video loaded, ground truth:', res && res.gt_loaded);
        this.startMission({ skipApplyConfig: true, isVideo: true });
      } catch (err) {
        console.error('Video load failed:', err);
        alert('Failed to load video: ' + err);
      }
      e.target.value = '';
    });
  }

  async startQuickDemo() {
    this.pages.missionConfig.motion = 'Straight';
    this.pages.missionConfig.speed = 'Normal';
    this.pages.missionConfig.position = 'near_center';
    this.pages.missionConfig.atmosphere = 'clear';
    this.pages.missionConfig.disturbances = [];
    this.pages.missionConfig.disturbanceIntensity = 0.0;
    this.pages.missionConfig.tracking = 'Hybrid';

    this.pages.missionConfig.renderer=this.sensorRenderer||'classic';
    await this.startMission();
  }

  loadVideo() {
    document.getElementById('video-file-input').click();
  }

  // ==================== HOME BUTTON ====================
  setupHomeButton() {
    const goHome = async () => {
      if(typeof CameraLabUI!=='undefined' && CameraLabUI.active) { await CameraLabUI.exit(); return; }
      try {
        const state=await API.getState();
        if(state.running) await API.command('stop');
      } catch (e) {
        console.error('Reset on home failed:', e);
      }
      this.pages.showPage('splash');
    };
    const navBtn = document.getElementById('nav-home-btn');
    if (navBtn) navBtn.addEventListener('click', goHome);
    const topbarHomeBtn = document.getElementById('btn-topbar-home');
    if (topbarHomeBtn) topbarHomeBtn.addEventListener('click', goHome);
  }

  // ==================== MISSION BUILDER ====================
  setupBuilder() {
    this._bindSingleSelect('#page-builder .motion-grid .option-tile', 'motion', (v) => this.pages.setMotion(v));
    this._bindSingleSelect('#speed-row .option-pill', 'speed', (v) => this.pages.setSpeed(v));
    this._bindSingleSelect('#position-row .option-pill', 'position', (v) => this.pages.setPosition(v));
    this._bindSingleSelect('#page-builder .atmosphere-grid .option-tile', 'atmosphere', (v) => this.pages.setAtmosphere(v));
    this._bindSingleSelect('#tracking-row .option-pill', 'tracking', (v) => this.pages.setTracking(v));

    document.querySelectorAll('#disturbance-row .option-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        chip.classList.toggle('selected');
        this.pages.toggleDisturbance(chip.dataset.disturbance);
        this._updateMissionSummary();
      });
    });

    const intensitySlider = document.getElementById('disturbance-intensity');
    intensitySlider.addEventListener('input', () => {
      const v = parseFloat(intensitySlider.value);
      document.getElementById('intensity-value').textContent = v.toFixed(2);
      this.pages.setDisturbanceIntensity(v);
      this._updateMissionSummary();
    });

    // Pre-select defaults matching missionConfig
    this._selectDefault('#page-builder .motion-grid .option-tile', 'motion', this.pages.missionConfig.motion);
    this._selectDefault('#speed-row .option-pill', 'speed', this.pages.missionConfig.speed);
    this._selectDefault('#position-row .option-pill', 'position', this.pages.missionConfig.position);
    this._selectDefault('#page-builder .atmosphere-grid .option-tile', 'atmosphere', this.pages.missionConfig.atmosphere);
    this._selectDefault('#tracking-row .option-pill', 'tracking', this.pages.missionConfig.tracking);

    this._updateMissionSummary();

    document.getElementById('btn-builder-next').addEventListener('click', () => {
      this._populateBrief();
      this.pages.showPage('brief');
    });
  }

  _bindSingleSelect(selector, attr, onSelect) {
    const els = document.querySelectorAll(selector);
    els.forEach(el => {
      el.addEventListener('click', () => {
        els.forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
        onSelect(el.dataset[attr]);
        this._updateMissionSummary();
      });
    });
  }

  _selectDefault(selector, attr, value) {
    document.querySelectorAll(selector).forEach(el => {
      el.classList.toggle('selected', el.dataset[attr] === value);
    });
  }

  _updateMissionSummary() {
    const el = document.getElementById('mission-summary-text');
    if (el) el.textContent = this.pages.buildMissionSummary();
  }

  // ==================== MISSION BRIEF ====================
  setupBrief() {
    document.getElementById('btn-start-mission').addEventListener('click', async () => {
      await this.startMission();
    });
  }

  async _populateBrief() {
    try {
      const state=await API.getState(), camera=state.camera_config || {};
      const fields={resolution: camera.width && camera.height ? `${camera.width} × ${camera.height}` : '—', hfov: camera.hfov == null ? '—' : `${camera.hfov.toFixed(1)}°`, vfov: camera.vfov == null ? '—' : `${camera.vfov.toFixed(1)}°`, update_rate:camera.update_rate == null ? '—' : `${camera.update_rate} Hz`, max_slew:camera.max_slew == null ? '—' : `${camera.max_slew.toFixed(1)}°/s`};
      Object.entries(fields).forEach(([key,value])=>{const el=document.getElementById(`brief-camera-${key}`);if(el)el.textContent=value;});
    } catch { /* Values remain unavailable until state is available. */ }

    const c = this.pages.missionConfig;
    document.getElementById('brief-motion').textContent = c.motion;
    document.getElementById('brief-speed').textContent = c.speed;
    document.getElementById('brief-position').textContent = c.position;
    document.getElementById('brief-atmosphere').textContent = this.pages.atmosphereLabel(c.atmosphere);
    document.getElementById('brief-disturbances').textContent = c.disturbances.length ? c.disturbances.join(', ') : 'None';
    document.getElementById('brief-intensity').textContent = c.disturbanceIntensity.toFixed(2);
    document.getElementById('brief-tracking').textContent = c.tracking;
  }

  async applyMissionConfigToBackend() {
    return API.post('/api/mission/configure', this.pages.missionConfig);
  }

  async _legacyApplyMissionConfigToBackend() {
    const c = this.pages.missionConfig;
    try {
      await API.setMotion(c.motion);
      const low = c.atmosphere === 'low_light';
      await API.setAtmosphere(low ? 'clear' : c.atmosphere);
      await API.setToggle('low_light', low);
      await API.setDetector(c.tracking);
      const allTypes = ['turbulence', 'vibration', 'noise', 'scintillation', 'jerk'];
      for (const type of allTypes) {
        const active = c.disturbances.includes(type);
        await API.setDisturbance(type, active ? c.disturbanceIntensity : 0.0);
      }
    } catch (e) {
      console.error('Failed to apply mission config:', e);
    }
  }

  // ==================== MISSION CONTROL ====================
  setupControl() {
    // Detector mode switches LIVE: backend resets tracker and starts new metrics session
    document.querySelectorAll('#control-tracking-row [data-tracking]').forEach(btn => {
      btn.addEventListener('click', () => {
        const mode = btn.dataset.tracking;
        document.querySelectorAll('#control-tracking-row [data-tracking]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.pages.setTracking(mode);
        API.setDetector(mode);
        this.logEvent(`Detector mode switched to ${mode}`);
      });
    });

    // View switching (Camera vs World)
    const switchCam = () => this._switchView('camera');
    const switchWld = () => this._switchView('world');
    const btnViewCam = document.getElementById('btn-view-camera');
    const btnViewWld = document.getElementById('btn-view-world');
    const btnBarCam = document.getElementById('btn-bar-camera');
    const btnBarWld = document.getElementById('btn-bar-world');
    const minimapCard = document.getElementById('minimap-inset');

    if (btnViewCam) btnViewCam.addEventListener('click', switchCam);
    if (btnViewWld) btnViewWld.addEventListener('click', switchWld);
    if (btnBarCam) btnBarCam.addEventListener('click', switchCam);
    if (btnBarWld) btnBarWld.addEventListener('click', switchWld);
    if (minimapCard) minimapCard.addEventListener('click', switchWld);

    // Right Panel Tabs
    ['telemetry', 'environment', 'events'].forEach(tab => {
      const tabBtn = document.getElementById(`tab-btn-${tab}`);
      if (tabBtn) tabBtn.addEventListener('click', () => this._switchTab(tab));
    });

    const btnEditDist = document.getElementById('btn-edit-disturbances');
    if (btnEditDist) btnEditDist.addEventListener('click', () => this._switchTab('environment'));
    const btnBarControls = document.getElementById('btn-bar-controls');
    if (btnBarControls) btnBarControls.addEventListener('click', () => this._switchTab('environment'));

    const btnClearLogs = document.getElementById('btn-clear-event-log');
    if (btnClearLogs) {
      btnClearLogs.addEventListener('click', () => {
        const stream = document.getElementById('event-log-stream');
        if (stream) stream.innerHTML = '';
        this.eventCount = 0;
        const cnt = document.getElementById('event-log-count');
        if (cnt) cnt.textContent = '0 events';
      });
    }

    // Live disturbances & atmosphere
    this._setupLiveDisturbances();

    // Target scenario motion buttons
    document.querySelectorAll('[data-scenario-motion]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const motion = btn.dataset.scenarioMotion;
        await API.setMotion(motion);
        this.logEvent(`Target motion pattern set to ${motion}`);
        document.querySelectorAll('[data-scenario-motion]').forEach(b => b.classList.toggle('active', b === btn));
      });
    });

    // Reset tracker button
    const btnResetTracker = document.getElementById('btn-reset-tracker');
    if (btnResetTracker) {
      btnResetTracker.addEventListener('click', async () => {
        await API.command('reset_tracker');
        this.logEvent('Tracker reset commanded');
      });
    }

    // Diagnostics button
    const btnDiag = document.getElementById('btn-diagnostics');
    if (btnDiag) btnDiag.addEventListener('click', () => this.showDiagnostics());

    document.getElementById('cam-rec')?.addEventListener('click', () => this.toggleRecording());

    // Stop, Pause, Screenshot buttons
    const btnStop = document.getElementById('btn-stop-mission');
    if (btnStop) btnStop.addEventListener('click', () => this.stopMission());

    const btnPause = document.getElementById('btn-pause-mission');
    if (btnPause) btnPause.addEventListener('click', () => this.togglePause());

    const btnScreenshot = document.getElementById('btn-screenshot');
    if (btnScreenshot) btnScreenshot.addEventListener('click', () => this.takeScreenshot());

    // Video replay controls
    const btnBackSim = document.getElementById('btn-back-sim');
    if (btnBackSim) btnBackSim.addEventListener('click', () => this.backToSimulation());
    const btnVBackSim = document.getElementById('btn-video-back-sim');
    if (btnVBackSim) btnVBackSim.addEventListener('click', () => this.backToSimulation());
    const btnVExpPdf = document.getElementById('btn-video-export-pdf');
    if (btnVExpPdf) {
      btnVExpPdf.addEventListener('click', () => {
        const p = this.currentState && this.currentState.last_report_path;
        if (p) window.open(API.logFileURL(p.split(/[\\/]/).pop()), '_blank');
      });
    }

    // Sliders
    const sInt = document.getElementById('live-slider-intensity');
    if (sInt) {
      sInt.addEventListener('input', () => {
        const v = parseFloat(sInt.value);
        const lVal = document.getElementById('slider-intensity-val');
        if (lVal) lVal.textContent = v.toFixed(2);
        this.pages.setDisturbanceIntensity(v);
      });
    }

    const sTurb = document.getElementById('live-slider-turbulence');
    if (sTurb) {
      sTurb.addEventListener('input', async () => {
        const v = parseFloat(sTurb.value);
        const lVal = document.getElementById('slider-turbulence-val');
        if (lVal) lVal.textContent = v.toFixed(2);
        await API.setDisturbance('turbulence', v);
      });
    }

    const sJitter = document.getElementById('live-slider-jitter');
    if (sJitter) {
      sJitter.addEventListener('input', async () => {
        const v = parseFloat(sJitter.value);
        const lVal = document.getElementById('slider-jitter-val');
        if (lVal) lVal.textContent = v.toFixed(2);
        await API.setDisturbance('vibration', v);
      });
    }
  }

  _switchTab(tab) {
    document.querySelectorAll('.panel-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.panel-tab-content').forEach(c => c.classList.toggle('active', c.id === `tab-content-${tab}`));
  }

  _switchView(view) {
    this._activeView = view;
    const camContainer = document.getElementById('camera-container');
    const wldContainer = document.getElementById('world-view-container');
    if (camContainer) camContainer.classList.toggle('view-active', view === 'camera');
    if (wldContainer) wldContainer.classList.toggle('view-active', view === 'world');

    const btnViewCam = document.getElementById('btn-view-camera');
    const btnViewWld = document.getElementById('btn-view-world');
    const btnBarCam = document.getElementById('btn-bar-camera');
    const btnBarWld = document.getElementById('btn-bar-world');
    if (btnViewCam) btnViewCam.classList.toggle('active', view === 'camera');
    if (btnViewWld) btnViewWld.classList.toggle('active', view === 'world');
    if (btnBarCam) btnBarCam.classList.toggle('active', view === 'camera');
    if (btnBarWld) btnBarWld.classList.toggle('active', view === 'world');
    if (view === 'world' && this.worldView && this.currentState) {
      this.worldView.updateViewport(this.currentState);
      for (const key of ['MinX','MinY','MaxX','MaxY']) this.worldView['view'+key]=this.worldView['target'+key];
      this.worldView.draw(this.currentState);
    }
  }

  logEvent(msg) {
    const stream = document.getElementById('event-log-stream');
    if (!stream) return;
    const elapsed = this.missionStartTime ? fmtElapsedWithTenths(Date.now() - this.missionStartTime) : '00:00.0';
    const item = document.createElement('div');
    item.className = 'event-item';
    item.innerHTML = `<span class="event-time">[${elapsed}]</span><span class="event-desc">${msg}</span>`;
    stream.appendChild(item);
    stream.scrollTop = stream.scrollHeight;
    this.eventCount = (this.eventCount || 0) + 1;
    const countEl = document.getElementById('event-log-count');
    if (countEl) countEl.textContent = `${this.eventCount} events`;
  }

  toggleRecording() {
    if (this.recorder) { this.recorder.stop(); return; }
    if (typeof MediaRecorder === 'undefined' || !HTMLCanvasElement.prototype.captureStream) {
      this.logEvent('Recording is unavailable in this browser'); return;
    }
    const source = document.getElementById('camera-feed');
    if (!source?.naturalWidth) { this.logEvent('Wait for a camera frame before recording'); return; }
    const canvas = document.createElement('canvas'); canvas.width=640; canvas.height=480;
    const ctx=canvas.getContext('2d'), stream=canvas.captureStream(0), track=stream.getVideoTracks()[0];
    const chunks=[], recorder=new MediaRecorder(stream);
    const paint=()=>{ctx.drawImage(source,0,0,640,480);const hud=document.getElementById('camera-hud-canvas');if(hud)ctx.drawImage(hud,0,0,640,480);track.requestFrame?.();};
    source.addEventListener('load',paint);
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=()=>{
      source.removeEventListener('load',paint);stream.getTracks().forEach(t=>t.stop());
      const url=URL.createObjectURL(new Blob(chunks,{type:recorder.mimeType}));
      const link=document.createElement('a');link.href=url;link.download=`FSOC_${this.currentState?.session_id || 'recording'}.webm`;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
      this.recorder=null;const button=document.getElementById('cam-rec');button.classList.remove('active');button.setAttribute('aria-pressed','false');
      this.logEvent('Recording stopped; WebM download requested');
    };
    this.recorder=recorder;this.recordingStart=this.currentState?.sim_time || 0;
    recorder.start(1000);paint();const button=document.getElementById('cam-rec');button.classList.add('active');button.setAttribute('aria-pressed','true');this.logEvent('Camera recording started');
  }

  takeScreenshot() {
    const isWorld = this._activeView === 'world';
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    const ctx = canvas.getContext('2d');

    if (isWorld) {
      const wv = document.getElementById('world-view');
      if (wv) ctx.drawImage(wv, 0, 0, 640, 480);
    } else {
      const img = document.getElementById('camera-feed');
      if (img && img.naturalWidth) {
        ctx.drawImage(img, 0, 0, 640, 480);
      } else {
        ctx.fillStyle = '#060d18';
        ctx.fillRect(0, 0, 640, 480);
      }
      const hud = document.getElementById('camera-hud-canvas');
      if (hud) ctx.drawImage(hud, 0, 0, 640, 480);
    }

    const link = document.createElement('a');
    link.download = `FSOC_Mission_${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    this.logEvent('Screenshot captured and saved');
  }

  showDiagnostics() {
    window.fsocDiagnostics?.toggle();
  }

  _legacyDiagnostics() {
    console.log('[Diagnostics] current state:', this.currentState);
    const s = this.currentState || {};
    const lines = [
      `FSOC-PAT System Diagnostics`,
      `-----------------------------------------`,
      `Track State:     ${s.track_state || 'UNKNOWN'}`,
      `Time in State:   ${s.current_state_time != null ? s.current_state_time.toFixed(1) + ' s' : '—'}`,
      `Track Error:     ${s.track_error_px != null ? s.track_error_px.toFixed(2) + ' px' : '—'} (${s.track_error_px != null ? Math.round(s.track_error_px * 109) + ' µrad' : '—'})`,
      `Confidence:      ${s.confidence != null ? (s.confidence * 100).toFixed(1) + '%' : '—'}`,
      `FPS:             ${s.fps != null ? Math.round(s.fps) : '—'}`,
      `Latency:         ${s.pipeline_ms != null ? Math.round(s.pipeline_ms) + ' ms' : (s.det_ms != null ? Math.round(s.det_ms) + ' ms' : '—')}`,
      `Detector:        ${s.detector_mode || 'Hybrid'}`,
      `Source:          ${s.video_mode ? 'VIDEO' : 'SIMULATION'}`,
      `Target Coord:    (${s.tracker_x != null ? s.tracker_x.toFixed(1) : '—'}, ${s.tracker_y != null ? s.tracker_y.toFixed(1) : '—'})`,
      `Predicted Coord: (${s.predicted_x != null ? s.predicted_x.toFixed(1) : '—'}, ${s.predicted_y != null ? s.predicted_y.toFixed(1) : '—'})`,
      `Pan / Tilt:      ${s.cam_pan != null ? s.cam_pan.toFixed(2) + '°' : '—'} / ${s.cam_tilt != null ? s.cam_tilt.toFixed(2) + '°' : '—'}`,
      `Atmosphere:      ${s.atmosphere || 'clear'}`,
      `Active Toggles:  ${s.toggles ? Object.keys(s.toggles).filter(k => s.toggles[k]).join(', ') || 'none' : 'none'}`
    ];
    alert(lines.join('\n'));
  }

  // Live disturbance buttons
  _setupLiveDisturbances() {
    document.querySelectorAll('[data-live-atm]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cur = (this.currentState && this.currentState.atmosphere) || 'clear';
        const want = btn.dataset.liveAtm;
        btn.classList.add('pending');
        try {
          const next = want === cur ? 'clear' : want;
          await API.setAtmosphere(next);
          this.logEvent(`Atmosphere set to ${next}`);
        } finally {
          await this.refreshDisturbanceUi();
          btn.classList.remove('pending');
        }
      });
    });

    document.querySelectorAll('[data-live-toggle]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.liveToggle;
        const t = (this.currentState && this.currentState.toggles) || {};
        const next = !t[name];
        btn.classList.add('pending');
        try {
          await API.setToggle(name, next);
          this.logEvent(`Disturbance toggle ${name} turned ${next ? 'ON' : 'OFF'}`);
        } finally {
          await this.refreshDisturbanceUi();
          btn.classList.remove('pending');
        }
      });
    });
  }

  async refreshDisturbanceUi() {
    try {
      const s = await API.getState();
      this.currentState = Object.assign({}, this.currentState || {}, s);
      this._syncDisturbanceUi(this.currentState);
    } catch (e) {
      console.error('[Disturbances] state read failed:', e);
    }
  }

  _syncDisturbanceUi(state) {
    if (!state || !state.toggles) return;
    const atm = state.atmosphere || 'clear';
    document.querySelectorAll('[data-live-atm]').forEach(b => {
      const on = b.dataset.liveAtm === atm;
      b.classList.toggle('active', on);
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-live-toggle]').forEach(b => {
      const on = !!state.toggles[b.dataset.liveToggle];
      b.classList.toggle('active', on);
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = on ? 'ON - click to turn off' : 'OFF - click to turn on';
    });

    // Sync mini disturbance grid in Telemetry tab
    const distMap = {
      gaussian: state.toggles.gaussian ? (state.disturbances?.noise ?? null) : 0,
      scintillation: state.disturbances ? (state.disturbances.scintillation || 0) : 0,
      saltpepper: !!state.toggles.saltpepper,
      turbulence: state.disturbances ? (state.disturbances.turbulence || 0) : 0,
      poisson: !!state.toggles.poisson,
      occlusion: !!state.toggles.occlusion,
      jitter: state.disturbances ? (state.disturbances.vibration || 0) : 0,
      decoys: !!state.toggles.decoys,
      low_light: !!state.toggles.low_light,
      platform: !!state.toggles.platform
    };

    Object.keys(distMap).forEach(key => {
      const val = distMap[key];
      const valEl = document.getElementById(`mini-val-${key}`);
      const barEl = document.getElementById(`mini-bar-${key}`);
      if (valEl) valEl.textContent = typeof val === 'boolean' ? (val ? 'ON' : 'OFF') : val == null ? '—' : val.toFixed(2);
      if (barEl) barEl.style.width = `${Math.min(100, Math.round(val * 100))}%`;
    });
  }

  async backToSimulation() {
    await API.setMode('simulation');
    this._videoUi = null;
    await this.startMission();
  }

  _applyVideoUi(state) {
    const video = !!state.video_mode;
    document.getElementById('page-control').classList.toggle('video-mode', video);
    const worldBtn = document.getElementById('btn-view-world');
    if (worldBtn) {
      worldBtn.disabled = video;
      worldBtn.style.opacity = video ? 0.4 : '';
      worldBtn.title = video ? 'No world map in video mode' : '';
    }
    const barWldBtn = document.getElementById('btn-bar-world');
    if (barWldBtn) {
      barWldBtn.disabled = video;
      barWldBtn.style.opacity = video ? 0.4 : '';
    }
    if (video && this._activeView === 'world') this._switchView('camera');

    const infoEl = document.getElementById('view-toggle-info');
    if (infoEl) {
      infoEl.textContent = video
        ? 'FIXED (video)'
        : 'Camera: 640×480px viewport into 2000×2000 world';
    }

    const backSim = document.getElementById('btn-back-sim');
    if (backSim) backSim.style.display = video ? '' : 'none';

    const errRow = document.getElementById('row-metric-error');
    if (errRow) errRow.style.display = '';
    document.querySelector('.minimap-inset-card').style.display = video ? 'none' : '';

    const ptRow = document.getElementById('row-pan-tilt');
    if (ptRow) ptRow.style.display = video ? 'none' : '';

    const cgtRow = document.getElementById('row-centroid-gt');
    if (cgtRow) cgtRow.style.display = video && state.video_gt_loaded ? '' : 'none';

    const done = video && !!state.video_done;
    const doneBanner = document.getElementById('video-done-banner');
    if (doneBanner) doneBanner.style.display = done ? '' : 'none';

    const expBtn = document.getElementById('btn-video-export-pdf');
    if (expBtn) expBtn.disabled = !(done && state.last_report_path);

    if (done) {
      const fpsEl = document.getElementById('cam-fps');
      if (fpsEl) fpsEl.textContent = '— FPS';
      const mfpsEl = document.getElementById('km-fps');
      if (mfpsEl) mfpsEl.textContent = '—';
      if (this.elapsedTimer) {
        clearInterval(this.elapsedTimer);
        this.elapsedTimer = null;
      }
    }
  }

  async startMission(opts = {}) {
    if (this.recorder) this.recorder.stop();
    if (!opts.isVideo) {
      const state = await API.getState();
      if(state.running) { const stopped=await API.command('stop'); if(stopped.status!=='ready')throw new Error(stopped.error||'Could not finish previous mission'); }
      if (!opts.skipApplyConfig) await this.applyMissionConfigToBackend();
      await API.command('reset');
      await new Promise(r => setTimeout(r, 500));
    }
    if (opts.isVideo && !opts.skipApplyConfig) {
      await this.applyMissionConfigToBackend();
    }
    await API.command('run');

    if (this.camera) this.camera.stop();
    this.camera = new CameraFeed(document.getElementById('camera-feed'));
    this.camera.start();

    if (this.worldView) this.worldView.reset();
    this.connectStateUpdates();

    const topRec = document.getElementById('cam-rec');
    if (topRec) topRec.classList.toggle('active', !!this.recorder);

    this.pages.showPage('control');
    document.getElementById('tab-btn-telemetry').click();
    const events = document.getElementById('event-log-stream');
    if (events) events.replaceChildren();
    this.eventCount = 0;
    this.missionStartTime = Date.now();
    this.isPaused = false;
    this.errorHistory = [];
    this.sparkData = { trackErr: [], acqTime: [], targetLoss: [], reacqTime: [], fps: [], lockRet: [] };
    this._lastTrackState = null;
    this._lastAtmosphere = null;

    this.logEvent(`Mission started (${opts.isVideo ? 'Video Replay' : 'Simulation'})`);

    if (this.elapsedTimer) clearInterval(this.elapsedTimer);
    this.elapsedTimer = setInterval(() => this._tickElapsed(), 500);
  }

  _tickElapsed() {
    if (!this.missionStartTime) return;
    const elapsed = this.currentState?.sim_time != null ? fmtElapsed(this.currentState.sim_time * 1000) : '—';
    const recTimer = document.getElementById('topbar-rec-timer');
    if (recTimer) recTimer.textContent = this.recorder && this.currentState?.sim_time != null ? fmtElapsed(Math.max(0, this.currentState.sim_time - this.recordingStart) * 1000) : '—';
  }

  connectStateUpdates() {
    if (this.stateWS) this.stateWS.close();
    this.stateWS = API.connectStateWS((state) => {
      this.currentState = state;
      const now = performance.now();
      if (now - (this._lastMetricsUpdate || 0) < 100) return;
      this._lastMetricsUpdate = now;
      this.updateMissionControl(state);
      this._syncDisturbanceUi(state);
    });
  }

  _drawCameraHud(state, trackState) {
    const canvas = document.getElementById('camera-hud-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    const cx = 320, cy = 240;

    // Center crosshair with 6px gap
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.45)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    // Horiz left
    ctx.moveTo(cx - 16, cy); ctx.lineTo(cx - 6, cy);
    // Horiz right
    ctx.moveTo(cx + 6, cy); ctx.lineTo(cx + 16, cy);
    // Vert top
    ctx.moveTo(cx, cy - 16); ctx.lineTo(cx, cy - 6);
    // Vert bottom
    ctx.moveTo(cx, cy + 6); ctx.lineTo(cx, cy + 16);
    ctx.stroke();

    // Center dot
    ctx.fillStyle = 'rgba(0, 240, 255, 0.6)';
    ctx.beginPath();
    ctx.arc(cx, cy, 1.5, 0, Math.PI * 2);
    ctx.fill();

    const tx = state.tracker_x;
    const ty = state.tracker_y;
    const px = state.predicted_x;
    const py = state.predicted_y;

    // Beacon ring & connecting line to center
    if (tx != null && ty != null && (trackState === 'LOCKED' || trackState === 'ACQUIRING' || trackState === 'COASTING')) {
      const ringColor = STATE_COLORS[trackState] || '#00d4ff';

      // Dashed line from center crosshair to beacon
      ctx.strokeStyle = 'rgba(0, 240, 255, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      ctx.setLineDash([]);

      // Distance annotation text at line midpoint
      if (state.track_error_px != null) {
        const mx = (cx + tx) / 2 + 5;
        const my = (cy + ty) / 2 - 5;
        ctx.fillStyle = 'rgba(0, 240, 255, 0.85)';
        ctx.font = '10px monospace';
        ctx.fillText(`${state.track_error_px.toFixed(1)} px`, mx, my);
      }

      // Beacon ring with subtle glow
      ctx.shadowColor = ringColor;
      ctx.shadowBlur = 6;
      ctx.strokeStyle = ringColor;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(tx, ty, 14, 0, Math.PI * 2);
      ctx.stroke();

      // Beacon center dot
      ctx.fillStyle = ringColor;
      ctx.beginPath();
      ctx.arc(tx, ty, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    // Predicted position marker: diamond shape at (predicted_x, predicted_y) labeled "prediction"
    if (px != null && py != null && (trackState === 'LOCKED' || trackState === 'COASTING' || trackState === 'ACQUIRING')) {
      const diamondColor = '#a78bfa'; // violet accent
      const r = 6;

      // Dashed line from beacon to prediction
      if (tx != null && ty != null) {
        ctx.strokeStyle = 'rgba(167, 139, 250, 0.5)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(px, py);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Diamond marker ◇
      ctx.strokeStyle = diamondColor;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(px, py - r);
      ctx.lineTo(px + r, py);
      ctx.lineTo(px, py + r);
      ctx.lineTo(px - r, py);
      ctx.closePath();
      ctx.stroke();

      // Label "prediction"
      ctx.fillStyle = 'rgba(6, 13, 24, 0.75)';
      ctx.fillRect(px + 8, py - 12, 60, 14);
      ctx.fillStyle = diamondColor;
      ctx.font = '9px monospace';
      ctx.fillText('prediction', px + 10, py - 2);
    }
  }

  _pushSpark(arr, val, maxLen = 30) {
    if (val == null || isNaN(val)) return;
    arr.push(val);
    if (arr.length > maxLen) arr.shift();
  }

  updateMissionControl(state) {
    const trackState = state.track_state || 'SEARCHING';
    const color = STATE_COLORS[trackState] || 'var(--text-primary)';
    const pipelineMs = state.pipeline_ms != null ? state.pipeline_ms : (state.det_ms != null ? state.det_ms : null);
    const timeInState = state.current_state_time != null ? state.current_state_time : 0;

    // 1. Top bar state pill
    const topbarPill = document.getElementById('topbar-state-pill');
    if (topbarPill) {
      topbarPill.className = `state-pill-large state-${trackState}`;
      const stateLbl = document.getElementById('topbar-state-label');
      if (stateLbl) stateLbl.textContent = trackState;
      const stateTmr = document.getElementById('topbar-state-timer');
      if (stateTmr) stateTmr.textContent = fmtElapsed(timeInState * 1000);
    }

    // Top bar source badge & Telemetry source
    const srcBadge = document.getElementById('topbar-source-badge');
    if (srcBadge) srcBadge.textContent = state.video_mode ? 'VIDEO' : 'SIM';
    const tscSrc = document.getElementById('tsc-source');
    if (tscSrc) tscSrc.textContent = state.video_mode ? 'VIDEO' : 'SIM';

    // Top bar latency
    const latVal = document.getElementById('topbar-latency-val');
    if (latVal) latVal.textContent = pipelineMs != null ? `${Math.round(pipelineMs)} ms` : '-- ms';
    const camLat = document.getElementById('cam-lat-val');
    if (camLat) camLat.textContent = pipelineMs != null ? `${Math.round(pipelineMs)} ms` : '-- ms';

    // Top bar session id
    const sessId = document.getElementById('control-session-id');
    if (sessId && state.session_id) sessId.textContent = state.session_id;

    // Top bar & Telemetry detector mode sync
    const mode = state.detector_mode || this.pages.missionConfig.tracking;
    if (mode !== this._activeDetectorMode) {
      this._activeDetectorMode = mode;
      this.pages.missionConfig.tracking = mode;
      document.querySelectorAll('#control-tracking-row [data-tracking]').forEach(b => {
        b.classList.toggle('active', b.dataset.tracking === mode);
      });
      const tscMode = document.getElementById('tsc-detector-mode');
      if (tscMode) tscMode.textContent = mode;
    }

    // 2. Camera HUD Overlay
    // HUD is painted after the next camera image finishes loading.

    // 3. Camera chips
    const camBadge = document.getElementById('cam-state-badge');
    if (camBadge) {
      camBadge.className = `cam-chip cam-chip-tl st-${trackState}`;
      const chipState = document.getElementById('cam-chip-state-text');
      if (chipState) chipState.textContent = trackState;
      const chipConf = document.getElementById('cam-chip-conf');
      if (chipConf) {
        chipConf.textContent = state.confidence != null ? `conf ${(state.confidence).toFixed(2)}` : 'conf —';
      }
    }
    const camFps = document.getElementById('cam-fps');
    if (camFps) camFps.textContent = state.fps != null ? `${Math.round(state.fps)} FPS` : '-- FPS';

    // 4. World View & Minimap
    if (!state.video_mode) {
      const minimap = document.getElementById('minimap-canvas');
      if (minimap && this.worldView && typeof this.worldView.drawMinimap === 'function') {
        this.worldView.drawMinimap(minimap, state);
      }
      if (this.worldView && this._activeView === 'world' && typeof this.worldView.draw === 'function') {
        this.worldView.draw(state);
      }
    }

    // 5. Telemetry Panel: Tracking State Card
    const rpState = document.getElementById('rp-state-text');
    if (rpState) {
      rpState.textContent = trackState;
      rpState.className = `tsc-state-val st-${trackState}`;
    }
    const rpEl = document.getElementById('rp-elapsed');
    if (rpEl) rpEl.textContent = fmtElapsed(timeInState * 1000);
    const updateRate = document.getElementById('tsc-update-rate');
    if (updateRate) updateRate.textContent = state.state_update_hz != null ? `${state.state_update_hz} Hz` : '—';

    // 6. Exactly 6 Key Metrics Rows
    // 1. Tracking error (limit <= 10 px)
    const errVal = state.track_error_px;
    const kmErrPx = document.getElementById('km-track-err-px');
    const kmErrUrad = document.getElementById('km-track-err-urad');
    const rowErr = document.getElementById('row-metric-error');
    if (kmErrPx) kmErrPx.textContent = errVal != null ? `${errVal.toFixed(1)} px` : '—';
    if (kmErrUrad) kmErrUrad.textContent = errVal != null ? `${Math.round(errVal * 109)} µrad` : '—';
    if (rowErr) {
      rowErr.classList.toggle('pass', errVal != null && errVal <= 10.0);
      rowErr.classList.toggle('fail', errVal != null && errVal > 10.0);
    }
    this._pushSpark(this.sparkData.trackErr, errVal);
    drawSparkline(document.getElementById('spark-track-err'), this.sparkData.trackErr, '#00d4ff', 'rgba(0,212,255,0.15)');

    // 2. Acquisition time (limit <= 2.0 s)
    const acqVal = state.acq_time;
    const kmAcq = document.getElementById('km-acq-time');
    const rowAcq = document.getElementById('row-metric-acq-time');
    if (kmAcq) kmAcq.textContent = acqVal != null ? `${acqVal.toFixed(2)} s` : '—';
    if (rowAcq) {
      rowAcq.classList.toggle('pass', acqVal != null && acqVal <= 2.0);
      rowAcq.classList.toggle('fail', acqVal != null && acqVal > 2.0);
    }
    this._pushSpark(this.sparkData.acqTime, acqVal);
    drawSparkline(document.getElementById('spark-acq-time'), this.sparkData.acqTime, '#38bdf8', 'rgba(56,189,248,0.15)');

    // 3. Target loss (limit < 5.0 %)
    const lossVal = state.target_loss;
    const kmLoss = document.getElementById('km-target-loss');
    const rowLoss = document.getElementById('row-metric-target-loss');
    if (kmLoss) kmLoss.textContent = lossVal != null ? `${lossVal.toFixed(1)} %` : '—';
    if (rowLoss) {
      rowLoss.classList.toggle('pass', lossVal != null && lossVal < 5.0);
      rowLoss.classList.toggle('fail', lossVal != null && lossVal >= 5.0);
    }
    this._pushSpark(this.sparkData.targetLoss, lossVal);
    drawSparkline(document.getElementById('spark-target-loss'), this.sparkData.targetLoss, '#f59e0b', 'rgba(245,158,11,0.15)');

    // 4. Re-acquisition time (limit <= 1.0 s)
    const reacqVal = state.reacq_time;
    const kmReacq = document.getElementById('km-reacq-time');
    const rowReacq = document.getElementById('row-metric-reacq-time');
    if (kmReacq) kmReacq.textContent = reacqVal != null ? `${reacqVal.toFixed(2)} s` : '—';
    if (rowReacq) {
      rowReacq.classList.toggle('pass', reacqVal != null && reacqVal <= 1.0);
      rowReacq.classList.toggle('fail', reacqVal != null && reacqVal > 1.0);
    }
    this._pushSpark(this.sparkData.reacqTime, reacqVal);
    drawSparkline(document.getElementById('spark-reacq-time'), this.sparkData.reacqTime, '#a78bfa', 'rgba(167,139,250,0.15)');

    // 5. Processing speed (FPS) (limit >= 20)
    const fpsVal = state.fps;
    const kmFps = document.getElementById('km-fps');
    const rowFps = document.getElementById('row-metric-fps');
    if (kmFps) kmFps.textContent = fpsVal != null ? `${Math.round(fpsVal)}` : '—';
    if (rowFps) {
      rowFps.classList.toggle('pass', fpsVal != null && fpsVal >= 20.0);
      rowFps.classList.toggle('fail', fpsVal != null && fpsVal < 20.0);
    }
    this._pushSpark(this.sparkData.fps, fpsVal);
    drawSparkline(document.getElementById('spark-fps'), this.sparkData.fps, '#00e699', 'rgba(0,230,153,0.15)');

    // 6. Lock retention (no limit)
    const lockVal = state.lock_rate;
    const kmLock = document.getElementById('km-lock-ret');
    const kmLockSrc = document.getElementById('km-lock-ret-source');
    if (kmLock) kmLock.textContent = lockVal != null ? `${(lockVal * 100).toFixed(1)} %` : '—';
    if (kmLockSrc) kmLockSrc.textContent = state.lock_rate_source === 'gt' ? 'ground truth' : 'tracker estimate';
    this._pushSpark(this.sparkData.lockRet, lockVal != null ? lockVal * 100 : null);
    drawSparkline(document.getElementById('spark-lock-ret'), this.sparkData.lockRet, '#38bdf8', 'rgba(56,189,248,0.15)');

    // 7. Video UI overrides
    this._applyVideoUi(state);

    // 8. Event log auto-tracking on transitions
    if (trackState !== this._lastTrackState) {
      if (this._lastTrackState) {
        this.logEvent(`Tracking state changed: ${this._lastTrackState} → ${trackState}`);
      }
      this._lastTrackState = trackState;
    }
    if (state.atmosphere && state.atmosphere !== this._lastAtmosphere) {
      if (this._lastAtmosphere) {
        this.logEvent(`Atmosphere changed to ${state.atmosphere}`);
      }
      this._lastAtmosphere = state.atmosphere;
    }

    // 9. Bottom timeline segmented display
    this._updateTimelineSegments(state, trackState);

    // 10. Error history for reporting
    if (state.sim_time != null) {
      this.errorHistory.push({ t: state.sim_time, error: state.track_error_px || 0 });
      if (this.errorHistory.length > 600) this.errorHistory.shift();
    }
  }

  _updateTimelineSegments(state, trackState) {
    const states = ['SEARCHING', 'ACQUIRING', 'LOCKED', 'COASTING', 'LOST'];
    const durations = state.state_durations || {};

    states.forEach(s => {
      const seg = document.getElementById(`tseg-${s}`);
      const dur = document.getElementById(`tdur-${s}`);
      if (seg) seg.classList.toggle('active', trackState === s);
      if (dur) {
        const d = durations[s];
        dur.textContent = d != null ? fmtDurationSec(d) : '--:--';
      }
    });
  }

  togglePause() {
    this.isPaused = !this.isPaused;
    API.command(this.isPaused ? 'pause' : 'run');
    const pIcon = document.getElementById('pause-icon');
    const pText = document.getElementById('pause-text');
    if (pIcon && pText) {
      pIcon.innerHTML = this.isPaused ? '&#9654;' : '&#10074;&#10074;';
      pText.textContent = this.isPaused ? 'Resume' : 'Pause';
    }
    this.logEvent(this.isPaused ? 'Mission paused' : 'Mission resumed');
  }

  async stopMission() {
    if(this._finalising)return;
    this._finalising=true;
    const stopButton=document.getElementById('btn-stop-mission'),oldLabel=stopButton?.innerHTML;
    if(stopButton){stopButton.disabled=true;stopButton.textContent='Saving results…';}
    try {
    if (this.recorder) this.recorder.stop();
    const result = await API.command('stop');
    if(result.status !== 'ready') { alert(result.error || 'Finalisation is still in progress. Please retry Stop.'); return; }
    if (this.camera) { this.camera.stop(); this.camera = null; }
    if (this.stateWS) { this.stateWS.close(); this.stateWS = null; }
    if (this.elapsedTimer) { clearInterval(this.elapsedTimer); this.elapsedTimer = null; }
    const topRec = document.getElementById('cam-rec');
    if (topRec) topRec.classList.remove('active');
    this.logEvent('Mission stopped');
    if(result.session_id) await SessionResults.open(result.session_id);
    else { this.pages.showPage('reports'); this.refreshReportsList(); }
    } catch(e) { alert('Results could not be saved: '+e.message+'. Retry Stop.'); }
    finally {this._finalising=false;if(stopButton){stopButton.disabled=false;stopButton.innerHTML=oldLabel;}}
  }

  // ==================== CAMERA LAB ====================
  setupCameraLab() {
    this._bindSingleSelect('#cameralab-tracking-row .option-pill', 'tracking', (v) => {
      this.pages.setTracking(v);
      API.setDetector(v);
    });
  }

  async startCameraLab() {
    await API.command('run');
    this.connectStateUpdates();
    if (this.labCamera) this.labCamera.stop();
    this.labCamera = new CameraFeed(document.getElementById('cameralab-feed'));
    this.labCamera.start();
    this.refreshDisturbanceUi();
    this.pages.showPage('cameralab');
  }

  // ==================== BENCHMARK ====================
  setupBenchmark() {
    document.getElementById('btn-run-benchmark').addEventListener('click', () => this.runBenchmark());
  }

  async runBenchmark() {
    if (this.benchmarkRunning) return;
    this.benchmarkRunning = true;
    this.benchmarkResults = [];
    document.getElementById('benchmark-table-body').innerHTML = '';

    // Mirrors server/app.py PRESETS — used only for the results table display
    // and pass/fail scoring; the actual settings are applied server-side by
    // API.setScenario(), this is not a second source of truth for the sim.
    const scenarios = {
      EASY: { label: 'EASY', motion: 'Straight', atmosphere: 'clear' },
      MOD:  { label: 'MODERATE', motion: 'Circular', atmosphere: 'haze' },
      HARD: { label: 'HARD', motion: 'Figure-8', atmosphere: 'fog' },
      SEV:  { label: 'SEVERE', motion: 'Random', atmosphere: 'rain' },
      ADV:  { label: 'ADVANCED', motion: 'Sinusoidal', atmosphere: 'low_light' }
    };
    const presets = Object.keys(scenarios);
    const durationMs = 60000;

    if (this.benchCamera) this.benchCamera.stop();
    this.benchCamera = new CameraFeed(document.getElementById('benchmark-feed'));
    this.benchCamera.start();

    for (const preset of presets) {
      document.querySelectorAll('.pipeline-step').forEach(el => {
        el.classList.remove('done', 'current', 'pending');
        const p = el.dataset.preset;
        if (presets.indexOf(p) < presets.indexOf(preset)) el.classList.add('done');
        else if (p === preset) el.classList.add('current');
        else el.classList.add('pending');
      });

      // Fresh state, then apply this scenario's settings, then go — each
      // gets its own metrics session (server resets rmse/lock_rate/acq_time
      // on 'reset') so scenarios never bleed into each other.
      await API.setScenario(preset);
      await API.command('reset');
      await new Promise(r => setTimeout(r, 800));
      await new Promise(r => setTimeout(r, 200));
      await API.command('run');

      document.getElementById('benchmark-current-name').textContent = scenarios[preset].label;

      // Sample live state once a second for the full 60s scenario window.
      const samples = [];
      const scenarioStart = Date.now();
      while (Date.now() - scenarioStart < durationMs) {
        let state;
        try {
          state = await API.getState();
        } catch (e) {
          state = {};
        }
        samples.push(state);

        const elapsed = Date.now() - scenarioStart;
        document.getElementById('benchmark-current-elapsed').textContent = fmtElapsed(elapsed);
        document.getElementById('benchmark-progress').style.width = `${Math.min(100, elapsed / durationMs * 100)}%`;
        document.getElementById('bench-metric-fps').textContent = state.fps != null ? Math.round(state.fps) : '—';
        document.getElementById('bench-metric-error').textContent = state.track_error_px != null ? state.track_error_px.toFixed(1) + ' px' : '—';
        document.getElementById('bench-metric-lock').textContent = state.lock_rate != null
          ? (state.lock_rate * 100).toFixed(1) + '%' + (state.lock_rate_source === 'gt' ? '' : ' (tracker estimate)') : '—';
        document.getElementById('bench-metric-state').textContent = state.track_state || '—';

        await new Promise(r => setTimeout(r, 1000));
      }

      const finished = await API.command('stop');
      if(finished.status !== 'ready' || !finished.session_id) {
        this.benchmarkRunning=false;
        if(this.benchCamera)this.benchCamera.stop();
        alert(finished.error || 'Benchmark finalisation failed. Retry Stop before another run.');
        return;
      }
      const record=await API.request('/api/sessions/'+finished.session_id);
      const s=record.summary, f=(v,u)=>v==null?'—':Number(v).toFixed(2)+u;
      const row = {scenario:scenarios[preset].label,environment:scenarios[preset].atmosphere,motion:scenarios[preset].motion,
        acqTime:f(s.acquisition_time_s,'s'),error:f(s.mean_track_error_px,'px'),loss:f(s.target_loss_pct,'%'),
        fps:f(s.mean_fps,''),status:record.requirements.overall};
      this.benchmarkResults.push(row);
      this._appendBenchmarkRow(row);
    }

    document.querySelectorAll('.pipeline-step').forEach(el => el.classList.add('done'));
    document.querySelectorAll('.pipeline-step').forEach(el => el.classList.remove('current', 'pending'));

    this.benchmarkRunning = false;
    if (this.benchCamera) { this.benchCamera.stop(); this.benchCamera = null; }
  }

  _appendBenchmarkRow(row) {
    const tbody = document.getElementById('benchmark-table-body');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.scenario}</td>
      <td>${row.environment}</td>
      <td>${row.motion}</td>
      <td>${row.acqTime}</td>
      <td>${row.error}</td>
      <td>${row.loss}</td>
      <td>${row.fps}</td>
      <td style="color:${row.status === 'PASS' ? 'var(--accent-green)' : 'var(--accent-red)'}">${row.status}</td>`;
    tbody.appendChild(tr);
  }

  // ==================== REPORTS ====================
  setupReports() {
    document.getElementById('btn-export-pdf').addEventListener('click', () => {
      if (this.selectedReport) {
        const pdf = this.selectedReport.replace(/_(frames|summary)\.csv$/i, '_report.pdf');
        window.open(API.logFileURL(pdf), '_blank');
      }
    });
    document.getElementById('btn-export-data').addEventListener('click', () => {
      if (this.selectedReport) window.open(API.logFileURL(this.selectedReport), '_blank');
    });
    document.getElementById('btn-share-report').addEventListener('click', () => {
      if (this.selectedReport) {
        const url = API.logFileURL(this.selectedReport);
        navigator.clipboard?.writeText(url).catch(() => {});
        alert('Report link copied:\n' + url);
      }
    });
  }

  async refreshReportsList() {
    return SessionResults.list();
  }

  async _legacyRefreshReportsList() {
    const listEl = document.getElementById('reports-list');
    try {
      const logs = await API.getLogs();
      listEl.innerHTML = '';
      logs.sort((a, b) => b.modified - a.modified);
      logs.forEach(log => {
        const item = document.createElement('div');
        item.className = 'report-item';
        item.textContent = log.name;
        const sizeSpan = document.createElement('span');
        sizeSpan.textContent = `${(log.size / 1024).toFixed(1)} KB`;
        item.appendChild(sizeSpan);
        item.addEventListener('click', () => this.selectReport(log.name, item));
        listEl.appendChild(item);
      });
      if (!logs.length) listEl.innerHTML = '<div class="report-item">No logs yet</div>';
    } catch (e) {
      listEl.innerHTML = '<div class="report-item">Failed to load logs</div>';
      console.error('Failed to load logs:', e);
    }
  }

  async selectReport(name, itemEl) {
    document.querySelectorAll('#reports-list .report-item').forEach(el => el.classList.remove('selected'));
    if (itemEl) itemEl.classList.add('selected');
    this.selectedReport = name;
    document.getElementById('reports-preview-title').textContent = name;

    if (!name.toLowerCase().endsWith('.csv')) {
      this._clearReportMetrics();
      return;
    }

    if (name.endsWith('_frames.csv')) {
      const summaryName = name.replace('_frames.csv', '_summary.csv');
      try {
        const summaryText = await API.getLogContent(summaryName);
        this._populateSummaryMetrics(this._parseSummaryCSV(summaryText));
      } catch (e) {
        this._clearReportMetrics();
      }
      try {
        const framesText = await API.getLogContent(name);
        const rows = this._parseFramesCSV(framesText);
        this._renderTimelineTable(rows);
        this._renderErrorChart(rows);
      } catch (e) {
        console.error('Failed to parse frames CSV:', e);
      }
    } else if (name.endsWith('_summary.csv')) {
      try {
        const summaryText = await API.getLogContent(name);
        this._populateSummaryMetrics(this._parseSummaryCSV(summaryText));
      } catch (e) {
        this._clearReportMetrics();
      }
    }
  }

  _clearReportMetrics() {
    ['report-metric-rmse', 'report-metric-lock', 'report-metric-acq', 'report-metric-maxerr'].forEach(id => {
      document.getElementById(id).textContent = '—';
    });
  }

  _parseSummaryCSV(text) {
    const lines = text.trim().split('\n').slice(1);
    const map = {};
    lines.forEach(line => {
      const [key, ...rest] = line.split(',');
      map[key] = rest.join(',');
    });
    return map;
  }

  _populateSummaryMetrics(summary) {
    document.getElementById('report-metric-rmse').textContent =
      summary.rmse_px ? parseFloat(summary.rmse_px).toFixed(1) + ' px' : '—';
    document.getElementById('report-metric-lock').textContent =
      summary.lock_rate_pct ? parseFloat(summary.lock_rate_pct).toFixed(1) + '%' : '—';
    document.getElementById('report-metric-acq').textContent =
      summary.acquisition_time_s ? parseFloat(summary.acquisition_time_s).toFixed(2) + 's' : '—';
    document.getElementById('report-metric-maxerr').textContent =
      summary.max_track_error_px ? parseFloat(summary.max_track_error_px).toFixed(1) + ' px' : '—';
  }

  _parseFramesCSV(text) {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return [];
    const header = lines[0].split(',');
    return lines.slice(1).map(line => {
      const cells = line.split(',');
      const row = {};
      header.forEach((h, i) => { row[h] = cells[i]; });
      return row;
    });
  }

  _renderTimelineTable(rows) {
    const tbody = document.getElementById('timeline-table-body');
    tbody.innerHTML = '';
    const step = Math.max(1, Math.floor(rows.length / 100));
    rows.filter((_, i) => i % step === 0).forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${parseFloat(row.timestamp_s || 0).toFixed(2)}s</td>
        <td>${row.state || '—'}</td>
        <td>${row.track_error_px ? parseFloat(row.track_error_px).toFixed(1) : '—'}</td>
        <td>${row.confidence ? (parseFloat(row.confidence) * 100).toFixed(0) + '%' : '—'}</td>`;
      tbody.appendChild(tr);
    });
  }

  _renderErrorChart(rows) {
    const ctx = document.getElementById('error-chart');
    if (!ctx || typeof Chart === 'undefined') return;
    const step = Math.max(1, Math.floor(rows.length / 200));
    const sampled = rows.filter((_, i) => i % step === 0);
    const labels = sampled.map(r => parseFloat(r.timestamp_s || 0).toFixed(1));
    const data = sampled.map(r => r.track_error_px ? parseFloat(r.track_error_px) : 0);

    if (this.chart) this.chart.destroy();
    this.chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Tracking Error (px)',
          data,
          borderColor: '#00d4ff',
          backgroundColor: 'rgba(0, 212, 255, 0.1)',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: '#94a3b8', maxTicksLimit: 10 }, grid: { color: 'rgba(30,58,95,0.3)' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(30,58,95,0.3)' } }
        },
        plugins: { legend: { labels: { color: '#e2e8f0' } } }
      }
    });
  }
}

// Initialize on load
const app = new FSocApp();
document.addEventListener('DOMContentLoaded', () => {
  app.init();
  document.getElementById('camera-feed')?.addEventListener('load', () => {
    const state = document.getElementById('camera-feed')._frameState;
    if (state && app.pages.currentPage === 'control') app._drawCameraHud(state, state.track_state);
  });
});
